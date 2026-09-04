"""Command line for the whole pipeline.

    python3 -m pspread.cli paraphrase --task mult --calls 60 --per-call 20
    python3 -m pspread.cli equiv      --task mult --sample 60
    python3 -m pspread.cli run        --task mult --model qwen3:8b
    python3 -m pspread.cli repeat     --task mult --model qwen3:8b --sample 200
    python3 -m pspread.cli analyze

Only `paraphrase` and `equiv` need network access to Gemini, and only `run` and `repeat` need
Ollama. `analyze` reads nothing but the committed files, which is what makes the published
numbers re-derivable without a GPU.
"""

import argparse
import datetime
import json
import pathlib
import random
import sys
from concurrent.futures import ThreadPoolExecutor

from . import features, grade, paraphrase, runner, stats, tasks

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
RAW = RESULTS / "raw"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def paraphrase_path(task_name):
    return RESULTS / f"paraphrases_{task_name}.json"


def load_paraphrases(task_name):
    d = json.loads(paraphrase_path(task_name).read_text(encoding="utf-8"))
    return d, [(p["id"], p["text"]) for p in d["paraphrases"]]


# --- generate ---------------------------------------------------------------------------

def cmd_paraphrase(args):
    task = tasks.get(args.task)
    path = paraphrase_path(task.name)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    kept = [] if existing is None else list(existing["paraphrases"])
    rejected = [] if existing is None else list(existing["rejected"])
    seen = {paraphrase.normalise(p["text"]) for p in kept}
    dupes = 0 if existing is None else existing["duplicates_dropped"]
    raw_n = 0 if existing is None else existing["raw_candidates"]

    if not kept:
        kept.append({"id": 0, "style": "canonical reference wording",
                     "text": task.canonical, "source": "author"})
        seen.add(paraphrase.normalise(task.canonical))

    next_id = max(p["id"] for p in kept) + 1
    rng = random.Random(args.seed)
    combos = [(s, a) for s in paraphrase.STYLES for a in paraphrase.AXES]
    rng.shuffle(combos)
    batches = [combos[i % len(combos)] for i in range(args.calls)]

    def fetch(job):
        style, axis, avoid = job
        prompt = paraphrase.build_prompt(task, style, args.per_call, axis, avoid)
        try:
            return style, paraphrase.call_generator(prompt, temperature=args.temperature)
        except RuntimeError as exc:
            print(f"  generator failed: {exc}", file=sys.stderr)
            return style, ""

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for start in range(0, len(batches), args.workers):
            wave = batches[start:start + args.workers]
            pool_of_texts = [p["text"] for p in kept]
            jobs = [(s, a, rng.sample(pool_of_texts, min(20, len(pool_of_texts))))
                    for s, a in wave]
            for style, text in pool.map(fetch, jobs):
                lines = [ln.strip().lstrip("-*0123456789.) ").strip()
                         for ln in text.splitlines() if ln.strip()]
                raw_n += len(lines)
                for line in lines:
                    reason = paraphrase.validate(line, task)
                    if reason:
                        rejected.append({"text": line[:300], "reason": reason})
                        continue
                    key = paraphrase.normalise(line)
                    if key in seen:
                        dupes += 1
                        continue
                    seen.add(key)
                    kept.append({"id": next_id, "style": style, "text": line,
                                 "source": "gemini"})
                    next_id += 1
            print(f"  {start + len(wave):4d}/{len(batches)} calls, pool={len(kept)}", flush=True)
            if args.target and len(kept) >= args.target:
                break

    _write(path, {
        "task": task.name,
        "canonical": task.canonical,
        "generated_at": _now(),
        "generator": {"model": paraphrase.GENERATOR_MODEL, "temperature": args.temperature,
                      "styles": paraphrase.STYLES, "axes": paraphrase.AXES,
                      "calls": args.calls, "per_call_request": args.per_call,
                      "avoid_list": "each call was shown 20 randomly chosen wordings already "
                                    "in the pool and told to differ from them"},
        "sampling_note": (
            "These wordings come from one model under one list of style directives chosen by "
            "the author. They are a sample from that generator, not a random sample of the "
            "phrasings a person would write, and the spread reported downstream is the spread "
            "over this pool."),
        "raw_candidates": raw_n,
        "duplicates_dropped": dupes,
        "rejected": rejected,
        "paraphrases": kept,
    })
    print(f"pool: {len(kept)} usable, {dupes} exact duplicates dropped, "
          f"{len(rejected)} rejected out of {raw_n} raw candidates")


# --- equivalence ------------------------------------------------------------------------

_BACKTRANSLATE = """Translate this instruction into Spanish. Output only the Spanish, one line.

{text}"""

_FORWARD = """Translate this Spanish instruction into English. Keep any {{placeholders}} exactly
as they are. Output only the English, one line.

{text}"""

_JUDGE = """Two instructions are below. Decide whether they ask for exactly the same thing, so
that any correct response to one would be a correct response to the other.

Differences in tone, length, politeness, register, or formatting do NOT matter.

Answer DIFFERENT if any of these is true:
- the candidate does not say which operation to perform, or names a different one
- the candidate leaves out information the reference gives, or adds information
- the candidate would accept an answer the reference would not, or the other way round
- the candidate is truncated, ungrammatical to the point of ambiguity, or asks two things

REFERENCE:
{a}

CANDIDATE:
{b}

Answer with one word, EQUIVALENT or DIFFERENT, then a semicolon, then a short reason.
"""


def cmd_equiv(args):
    """Judge EVERY paraphrase against the canonical wording, not a sample of them.

    The reason this is exhaustive is a wording the pool actually contained: "You are an
    efficient processor. Give the result of the calculation as a raw integer with no commas or
    non-numeric text: {a} and {b}". It never says which calculation. It scored 4% on qwen3:8b
    because the model concatenated the two numbers, and counting that as a wording effect would
    have inflated the headline range with a prompt that is not a paraphrase at all.

    A sampled check would have reported a high equivalence rate and left the bad wording in the
    distribution, so the sample is not enough. The back-translation round trip stays a sample,
    because it costs three calls per wording and it is a check on the meaning surviving a
    transform rather than a filter on the pool.
    """
    task = tasks.get(args.task)
    meta, pairs = load_paraphrases(task.name)
    canonical = task.canonical.replace("\n\n", " ")

    def judge(job):
        pid, text = job
        try:
            v = paraphrase.call_generator(
                _JUDGE.format(a=canonical, b=text), temperature=0.0).strip()
        except RuntimeError as exc:
            return {"id": pid, "verdict": "UNJUDGED", "reason": str(exc)[:200], "text": text}
        return {"id": pid, "verdict": v.split(";")[0].strip().upper()[:12],
                "reason": v.split(";", 1)[1].strip()[:200] if ";" in v else "",
                "text": text}

    todo = [(pid, text) for pid, text in pairs if pid != 0]
    judged = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(judge, todo), 1):
            judged.append(res)
            if i % 50 == 0:
                print(f"  judged {i}/{len(todo)}", flush=True)
    judged.sort(key=lambda j: j["id"])

    rng = random.Random(args.seed)
    bt_sample = rng.sample(todo, min(args.backtranslate, len(todo)))

    def roundtrip(job):
        pid, text = job
        try:
            es = paraphrase.call_generator(
                _BACKTRANSLATE.format(text=text), temperature=0.0).strip()
            en = paraphrase.call_generator(_FORWARD.format(text=es), temperature=0.0).strip()
            v = paraphrase.call_generator(_JUDGE.format(a=text, b=en), temperature=0.0).strip()
        except RuntimeError as exc:
            return {"id": pid, "original": text, "verdict": "UNJUDGED",
                    "reason": str(exc)[:200], "slots_survived": False}
        return {"id": pid, "original": text, "spanish": es[:400], "back": en[:400],
                "verdict": v.split(";")[0].strip().upper()[:12],
                "slots_survived": paraphrase.validate(en, task) is None}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        backtranslated = sorted(pool.map(roundtrip, bt_sample), key=lambda b: b["id"])

    equiv_n = sum(1 for j in judged if j["verdict"].startswith("EQUIV"))
    unjudged = [j["id"] for j in judged if j["verdict"] == "UNJUDGED"]
    bt_ok = sum(1 for b in backtranslated if b["verdict"].startswith("EQUIV"))
    _write(RESULTS / f"equivalence_{task.name}.json", {
        "task": task.name,
        "checked_at": _now(),
        "judge_model": paraphrase.GENERATOR_MODEL,
        "method": (
            "Three checks. A deterministic structural check ran on every candidate at generation "
            "time and is the reason the rejected list exists. A model judge compared EVERY "
            "wording against the canonical one, and the analysis uses only the wordings it "
            "called equivalent. A round trip through Spanish and back, on a random sample, "
            "judged against its own original, tests whether the meaning survives a transform "
            "that does not preserve surface form."),
        "reviewer_note": (
            "The judge is a language model, and the spot-check of its verdicts was done by an "
            "AI agent. No human read these wordings."),
        "judged": {"n": len(judged), "equivalent": equiv_n,
                   "unjudged": len(unjudged),
                   "rate": equiv_n / len(judged) if judged else None},
        "backtranslation": {"n": len(backtranslated), "equivalent": bt_ok,
                            "rate": bt_ok / len(backtranslated) if backtranslated else None,
                            "slots_survived": sum(b["slots_survived"]
                                                  for b in backtranslated)},
        "structural_rejections": len(meta["rejected"]),
        "equivalent_ids": [0] + [j["id"] for j in judged if j["verdict"].startswith("EQUIV")],
        "judgements": judged,
        "backtranslations": backtranslated,
    })
    print(f"judge: {equiv_n}/{len(judged)} equivalent, {len(unjudged)} could not be judged. "
          f"back-translation: {bt_ok}/{len(backtranslated)} equivalent.")


# --- run --------------------------------------------------------------------------------

def cmd_run(args):
    task = tasks.get(args.task)
    _, pairs = load_paraphrases(task.name)
    if args.max_paraphrases:
        pairs = pairs[:args.max_paraphrases]
    print(f"{task.name}: {len(pairs)} paraphrases x {len(task.items)} items on {args.model}")
    # Written before the run rather than after, so a run that is interrupted still leaves the
    # mapping from file-name slug back to the real model id. Without it the analysis labels a
    # partial run with the slug, and the published model name is then subtly wrong.
    meta_path = RAW / f"{task.name}__{runner.model_slug(args.model)}__meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"runs": []}
    meta.update({"task": task.name, "model": args.model, "options": runner.OPTIONS,
                 "items": len(task.items)})
    _write(meta_path, meta)

    def progress(n, total, rate, errors):
        eta = (total - n) / rate if rate else 0
        print(f"  {n:6d}/{total} {rate:5.2f}/s errors={errors} eta={eta / 60:.1f}m", flush=True)

    summary = runner.run(task, pairs, args.model, RAW, workers=args.workers,
                         limit=args.limit, progress=progress)
    print(json.dumps(summary, indent=1))
    if args.unload:
        runner.unload(args.model)
    meta = json.loads(meta_path.read_text())
    meta["runs"].append({"at": _now(), **summary})
    _write(meta_path, meta)


def cmd_repeat(args):
    """Re-ask a sample of already-answered prompts and measure how often the reply is identical.

    Temperature 0 is not a promise of determinism from a batching server, so the analysis says
    the responses are deterministic only to the extent this measures them to be.
    """
    task = tasks.get(args.task)
    _, pairs = load_paraphrases(task.name)
    templates = dict(pairs)
    items = {i.key: i for i in task.items}
    _, records = runner.load_done(RAW, task.name, args.model)
    records = [r for r in records if r.get("r") is not None]
    rng = random.Random(args.seed)
    sample = rng.sample(records, min(args.sample, len(records)))
    same = 0
    diffs = []
    for rec in sample:
        prompt = templates[rec["p"]].format(**items[rec["i"]].slots)
        text, _, err = runner.generate(args.model, prompt)
        if err:
            continue
        if text == rec["r"]:
            same += 1
        elif len(diffs) < 12:
            diffs.append({"p": rec["p"], "i": rec["i"], "first": rec["r"][:160],
                          "second": text[:160]})
    out = {"task": task.name, "model": args.model, "checked_at": _now(), "n": len(sample),
           "identical": same, "rate": same / len(sample) if sample else None,
           "examples_of_disagreement": diffs}
    _write(RESULTS / f"repeat_{task.name}__{runner.model_slug(args.model)}.json", out)
    print(f"{same}/{len(sample)} responses reproduced byte for byte")


# --- analyze ----------------------------------------------------------------------------

def analyse_one(task, model, permutations=1000, splits=200):
    meta, pairs = load_paraphrases(task.name)
    templates = dict(pairs)
    styles = {p["id"]: p["style"] for p in meta["paraphrases"]}
    answers = {i.key: i.answer for i in task.items}
    item_keys = [i.key for i in task.items]

    _, records = runner.load_done(RAW, task.name, model)
    if not records:
        return None
    by_pid = {}
    for r in records:
        by_pid.setdefault(r["p"], []).append((r["i"], r.get("r")))

    # A paraphrase is only usable if it has a response for every item AND none of those calls
    # failed. The correctness matrix has one column per item and no way to say "no data", so an
    # errored cell would enter it as a wrong answer and count against the wording for a reason
    # that has nothing to do with the wording. Dropping the whole row keeps every paraphrase
    # scored on exactly the same 24 items, and the number dropped is reported rather than
    # absorbed.
    graded, per_paraphrase, dropped_for_failed_calls = {}, [], []
    for pid, recs in sorted(by_pid.items()):
        if len(recs) < len(item_keys):
            continue
        g = grade.grade_group(recs, answers, task.answer_kind)
        if g["error"]:
            dropped_for_failed_calls.append(pid)
            continue
        graded[pid] = g
        per_paraphrase.append((pid, g["per_item"]))
    if not per_paraphrase:
        return None

    all_ids, _ = stats.to_matrix(per_paraphrase, item_keys)
    unfiltered = stats.describe([graded[pid]["strict_accuracy"] for pid in all_ids])

    # Only wordings the equivalence judge cleared enter the headline distribution. A wording that
    # dropped the operation is not a paraphrase, and leaving it in would credit the spread to
    # wording when the cause is a changed question. The unfiltered figures stay in the output so
    # the size of that correction is visible rather than quietly applied.
    eq_path = RESULTS / f"equivalence_{task.name}.json"
    if eq_path.exists():
        eq = json.loads(eq_path.read_text(encoding="utf-8"))
        verified = set(eq["equivalent_ids"])
        equivalence_note = (
            f"{eq['judged']['equivalent']} of {eq['judged']['n']} wordings were judged "
            f"equivalent to the reference by {eq['judge_model']}; the rest are excluded here")
    else:
        verified = None
        equivalence_note = ("no equivalence check has been run, so every wording is included "
                            "and the spread may contain prompts that changed the question")

    per_paraphrase = [(pid, pi) for pid, pi in per_paraphrase
                      if verified is None or pid in verified]
    ids, rows = stats.to_matrix(per_paraphrase, item_keys)
    accs = [graded[pid]["strict_accuracy"] for pid in ids]
    lenient = [graded[pid]["lenient_accuracy"] for pid in ids]
    parsed = [graded[pid]["parsed_accuracy"] for pid in ids
              if graded[pid]["parsed_accuracy"] is not None]

    best = max(ids, key=lambda p: graded[p]["strict_accuracy"])
    worst = min(ids, key=lambda p: graded[p]["strict_accuracy"])

    feat_rows = {name: [] for name in features.NAMES}
    for pid in ids:
        f = features.extract(templates[pid])
        for name in features.NAMES:
            feat_rows[name].append(f[name])
    raw_p, rhos = [], {}
    for name in features.NAMES:
        xs = feat_rows[name]
        if len(set(xs)) < 2:
            rhos[name] = None
            raw_p.append(1.0)
            continue
        rhos[name] = stats.spearman(xs, accs)
        raw_p.append(stats.spearman_permutation_p(xs, accs, reps=2000))
    adj = stats.holm(raw_p)

    total_attempts = sum(graded[p]["attempts"] for p in ids)
    return {
        "task": task.name,
        "model": model,
        "equivalence_note": equivalence_note,
        "paraphrases_dropped_for_failed_calls": len(dropped_for_failed_calls),
        "paraphrases_before_equivalence_filter": len(all_ids),
        "unfiltered": unfiltered,
        "paraphrases_scored": len(ids),
        "items": len(item_keys),
        "responses": total_attempts,
        "accounting": {
            "correct": sum(graded[p]["correct"] for p in ids),
            "wrong": sum(graded[p]["wrong"] for p in ids),
            "unparseable": sum(graded[p]["unparseable"] for p in ids),
            "error": sum(graded[p]["error"] for p in ids),
        },
        "strict": stats.describe(accs),
        "parsed_only": stats.describe(parsed),
        "lenient": stats.describe(lenient),
        # One bin per attainable score. With 24 items a wording can only land on one of
        # 25 values, and binning them any other way invents structure.
        "histogram": stats.histogram(accs, lo=-0.5 / len(item_keys),
                                     hi=1 + 0.5 / len(item_keys), bins=len(item_keys) + 1),
        "canonical_accuracy": graded[0]["strict_accuracy"] if 0 in graded else None,
        "canonical_percentile": (
            sum(1 for a in accs if a <= graded[0]["strict_accuracy"]) / len(accs)
            if 0 in graded else None),
        "best": {"id": best, "accuracy": graded[best]["strict_accuracy"],
                 "text": templates[best]},
        "worst": {"id": worst, "accuracy": graded[worst]["strict_accuracy"],
                  "text": templates[worst]},
        "spread_test": stats.spread_test(rows, reps=permutations),
        "reliability": stats.split_half_reliability(rows, reps=splits),
        "features": [
            {"name": n, "description": features.DESCRIPTIONS[n], "spearman": rhos[n],
             "p_raw": raw_p[i], "p_holm": adj[i],
             "share_with_feature": stats.mean(1.0 if v else 0.0 for v in feat_rows[n])
             if set(feat_rows[n]) <= {0.0, 1.0} else None}
            for i, n in enumerate(features.NAMES)],
        "per_paraphrase": [
            {"id": pid, "accuracy": graded[pid]["strict_accuracy"],
             "parsed_accuracy": graded[pid]["parsed_accuracy"],
             "unparseable": graded[pid]["unparseable"], "style": styles[pid]}
            for pid in ids],
    }


def cmd_analyze(args):
    # NO TIMESTAMP ON THE ANALYSIS. The corpus keeps its `generated_at`, because when the model
    # outputs were collected is real provenance and nothing can recompute it. The analysis is a
    # pure re-derivation from that committed corpus, so a timestamp on it records only when
    # somebody last ran the command, and it made `analysis.json` come back modified after every
    # run. `scripts/verify.sh` had to pop the field before comparing, which is the shape of a
    # problem being worked around rather than fixed.
    out = {"runs": []}
    for task_name, model in _discover_runs():
        task = tasks.get(task_name)
        print(f"analysing {task_name} on {model} ...", flush=True)
        res = analyse_one(task, model, permutations=args.permutations, splits=args.splits)
        if res:
            out["runs"].append(res)
    out["tasks"] = {name: {"blurb": t.blurb, "canonical": t.canonical,
                           "items": len(t.items), "answer_kind": t.answer_kind}
                    for name, t in tasks.TASKS.items()}
    _write(RESULTS / "analysis.json", out)
    for r in out["runs"]:
        s = r["strict"]
        q_p = r["spread_test"]["q_p_value"]
        print(f"  {r['task']:8s} {r['model']:14s} n={s['n']:4d} mean={s['mean']:.3f} "
              f"sd={s['sd']:.3f} range={s['min']:.3f}..{s['max']:.3f} "
              f"q_p={'undefined' if q_p is None else format(q_p, '.4f')} "
              f"rel={r['reliability']['spearman_brown']:.2f}")


def _discover_runs():
    found = set()
    for path in RAW.glob("*__*.jsonl"):
        stem = path.stem
        task_name, rest = stem.split("__", 1)
        model_slug = rest.rsplit("__", 1)[0]
        found.add((task_name, model_slug))
    unslug = {}
    for path in RAW.glob("*__meta.json"):
        meta = json.loads(path.read_text())
        unslug[runner.model_slug(meta["model"])] = meta["model"]
    return sorted((t, unslug.get(m, m)) for t, m in found)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pspread")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("paraphrase")
    p.add_argument("--task", required=True)
    p.add_argument("--per-call", type=int, default=20)
    p.add_argument("--calls", type=int, default=60)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=31)
    p.add_argument("--target", type=int, default=0)
    p.add_argument("--temperature", type=float, default=1.0)
    p.set_defaults(fn=cmd_paraphrase)

    p = sub.add_parser("equiv")
    p.add_argument("--task", required=True)
    p.add_argument("--backtranslate", type=int, default=40)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=17)
    p.set_defaults(fn=cmd_equiv)

    p = sub.add_parser("run")
    p.add_argument("--task", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-paraphrases", type=int, default=None)
    p.add_argument("--unload", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("repeat")
    p.add_argument("--task", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--sample", type=int, default=200)
    p.add_argument("--seed", type=int, default=23)
    p.set_defaults(fn=cmd_repeat)

    p = sub.add_parser("analyze")
    p.add_argument("--permutations", type=int, default=1000)
    p.add_argument("--splits", type=int, default=200)
    p.set_defaults(fn=cmd_analyze)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
