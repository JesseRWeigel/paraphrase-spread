#!/usr/bin/env python3
"""Re-derive the headline numbers from the raw responses, sharing no code with the pipeline.

This file imports nothing from `pspread/`. Not the grader, not the statistics, not the task
definitions. `scripts/verify.sh` proves that by parsing this file's import graph with `ast`
rather than by trusting the sentence you just read.

Three things are re-derived from scratch:

  THE ANSWER KEY, from the item identifiers rather than from `pspread.tasks`. `mult-79x92` means
  79 times 92, and the four `entail` prefixes name the argument form, whose correct answer is
  fixed by classical logic: modus ponens yes, modus tollens no, and the two fallacies unknown.
  If the task module's answer key were wrong, importing it would reproduce the error.

  THE GRADE, by scanning characters rather than by matching regular expressions, following the
  extraction specification written at the top of `pspread/grade.py`. Two implementations of one
  precise spec should agree exactly, so this demands exact agreement and not a tolerance.

  THE STATISTICS, with their own arithmetic: mean, population standard deviation, min, max, and
  Cochran's Q. The permutation p-values are not compared, because those depend on a random seed
  and comparing them would only prove that two runs used the same generator.

Usage:  check_independent.py [--results DIR] [--verbose]
Exit 0 if every re-derived number matches what analysis.json claims, 1 otherwise.
"""

import argparse
import json
import os
import sys

DIGITS = "0123456789"
LETTERS = set("abcdefghijklmnopqrstuvwxyz0123456789_")
LABELS = ("unknown", "yes", "no")
FORM_ANSWER = {"mp": "yes", "mt": "no", "ac": "unknown", "da": "unknown"}


# --- the answer key, rebuilt from the item identifiers -----------------------------------

def answer_for(item_key):
    if item_key.startswith("mult-"):
        left, right = item_key[5:].split("x")
        return str(int(left) * int(right)), "integer"
    prefix = item_key.split("-")[0]
    if prefix in FORM_ANSWER:
        return FORM_ANSWER[prefix], "label"
    raise ValueError(f"cannot rebuild an answer for item {item_key!r}")


# --- extraction, by character scan ---------------------------------------------------------

def numbers_in(text):
    """Every maximal digit run, after deleting commas that sit between two digits."""
    kept = []
    for i, ch in enumerate(text):
        if ch == "," and 0 < i < len(text) - 1 and text[i - 1] in DIGITS and text[i + 1] in DIGITS:
            continue
        kept.append(ch)
    out, current = [], ""
    for ch in kept:
        if ch in DIGITS:
            current += ch
        elif current:
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return out


def labels_in(text):
    """Every whole-word yes / no / unknown, in order of appearance."""
    low = text.lower()
    found = []
    i = 0
    while i < len(low):
        matched = None
        for word in LABELS:
            if low.startswith(word, i):
                before_ok = i == 0 or low[i - 1] not in LETTERS
                after = i + len(word)
                after_ok = after == len(low) or low[after] not in LETTERS
                if before_ok and after_ok:
                    matched = word
                    break
        if matched:
            found.append(matched)
            i += len(matched)
        else:
            i += 1
    return found


def verdict(text, answer, kind):
    """Returns one of correct / wrong / unparseable / error, plus the lenient flag."""
    if text is None:
        return "error", False
    cands = numbers_in(text) if kind == "integer" else labels_in(text)
    if not cands:
        return "unparseable", False
    if kind == "integer":
        hit = [c for c in cands if int(c) == int(answer)]
        last_ok = int(cands[-1]) == int(answer)
    else:
        hit = [c for c in cands if c == answer]
        last_ok = cands[-1] == answer
    return ("correct" if last_ok else "wrong"), bool(hit)


# --- statistics, with their own arithmetic ------------------------------------------------

def avg(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def popsd(xs):
    xs = list(xs)
    m = avg(xs)
    return (sum((x - m) * (x - m) for x in xs) / len(xs)) ** 0.5


def cochran(rows):
    k = len(rows)
    b = len(rows[0])
    per_paraphrase = [sum(r) for r in rows]
    per_item = [sum(row[i] for row in rows) for i in range(b)]
    g = avg(per_paraphrase)
    denominator = k * sum(per_item) - sum(x * x for x in per_item)
    if denominator == 0:
        return None
    return k * (k - 1) * sum((x - g) * (x - g) for x in per_paraphrase) / denominator


# --- reading the raw files -----------------------------------------------------------------

def read_raw(raw_dir, task, model_slug):
    prefix = f"{task}__{model_slug}__"
    rows = []
    for name in sorted(os.listdir(raw_dir)):
        if name.startswith(prefix) and name.endswith(".jsonl"):
            with open(os.path.join(raw_dir, name), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
    return rows


def slugify(model):
    return model.replace(":", "-").replace("/", "-")


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    results = os.path.abspath(args.results)
    raw_dir = os.path.join(results, "raw")
    analysis = json.load(open(os.path.join(results, "analysis.json"), encoding="utf-8"))

    if not analysis.get("runs"):
        print("analysis.json contains no runs, so there is nothing to check")
        return 1

    problems = []
    for claimed in analysis["runs"]:
        task = claimed["task"]
        model = claimed["model"]
        rows = read_raw(raw_dir, task, slugify(model))
        if not rows:
            problems.append(f"{task}/{model}: no raw responses found")
            continue

        by_pid = {}
        for r in rows:
            by_pid.setdefault(r["p"], {})[r["i"]] = r.get("r")

        item_keys = sorted({r["i"] for r in rows})
        expected_items = claimed["items"]
        if len(item_keys) != expected_items:
            problems.append(f"{task}/{model}: raw files hold {len(item_keys)} distinct items, "
                            f"analysis claims {expected_items}")

        counts = {"correct": 0, "wrong": 0, "unparseable": 0, "error": 0}
        lenient_total = 0
        accs, matrix, complete = [], [], []
        for pid in sorted(by_pid):
            per_item = by_pid[pid]
            if len(per_item) < len(item_keys):
                continue
            row, ncorrect, nscored, nlenient = [], 0, 0, 0
            for key in item_keys:
                ans, kind = answer_for(key)
                v, lenient = verdict(per_item[key], ans, kind)
                counts[v] += 1
                lenient_total += int(lenient)
                row.append(1 if v == "correct" else 0)
                if v != "error":
                    nscored += 1
                    nlenient += int(lenient)
                if v == "correct":
                    ncorrect += 1
            if nscored == 0:
                continue
            complete.append(pid)
            matrix.append(row)
            accs.append(ncorrect / nscored)

        got = {
            "paraphrases_scored": len(complete),
            "responses": sum(counts.values()),
            "mean": avg(accs),
            "sd": popsd(accs),
            "min": min(accs),
            "max": max(accs),
            "range": max(accs) - min(accs),
            "cochran_q": cochran(matrix),
        }
        want = {
            "paraphrases_scored": claimed["paraphrases_scored"],
            "responses": claimed["responses"],
            "mean": claimed["strict"]["mean"],
            "sd": claimed["strict"]["sd"],
            "min": claimed["strict"]["min"],
            "max": claimed["strict"]["max"],
            "range": claimed["strict"]["range"],
            "cochran_q": claimed["spread_test"]["cochran_q"],
        }
        for key in want:
            a, b = got[key], want[key]
            same = (a == b) if isinstance(b, int) and isinstance(a, int) else close(a, b)
            if not same:
                problems.append(f"{task}/{model}: {key} re-derived as {a!r}, "
                                f"analysis.json says {b!r}")
        for key in ("correct", "wrong", "unparseable", "error"):
            if counts[key] != claimed["accounting"][key]:
                problems.append(f"{task}/{model}: {key} re-derived as {counts[key]}, "
                                f"analysis.json says {claimed['accounting'][key]}")
        if not close(got["sd"], claimed["spread_test"]["observed_sd"]):
            problems.append(f"{task}/{model}: spread_test.observed_sd disagrees with the "
                            f"standard deviation of the per-paraphrase accuracies")

        print(f"  {task}/{model}: {sum(counts.values()):,} responses re-graded, "
              f"{len(complete)} paraphrases, mean {got['mean']:.4f}, sd {got['sd']:.4f}, "
              f"range {got['min']:.4f}..{got['max']:.4f}, Q {got['cochran_q']:.1f}")
        if args.verbose:
            print(f"        accounting {counts}, lenient {lenient_total}")

    if problems:
        print("\nDISAGREEMENT between the independent re-derivation and analysis.json:")
        for p in problems:
            print("  " + p)
        return 1
    print("every headline number re-derived from the raw responses agrees exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
