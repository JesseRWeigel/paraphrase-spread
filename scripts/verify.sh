#!/usr/bin/env bash
# Verification for paraphrase-spread.
#
# The claim this project makes is a distribution: one task, many wordings, and a wide range of
# accuracy across them. The failure that would matter is not a crash. It is a confident spread
# that is really an artefact of a grader that reads the wrong end of a response, or of a
# statistic that would report a spread on data containing none. So the layers aim there.
#
#   1  unit suite, every test paired with a negative control
#   2  that pairing checked structurally, so a control cannot quietly go missing
#   3  the raw responses are present and complete, and a missing one FAILS rather than skips
#   4  analysis.json rebuilt from the raw responses and compared field by field
#   5  every headline number re-derived by code that shares nothing with the pipeline
#   6  that independence proved by walking the import graph with ast
#   7  the same re-derivation run against a broken grader, which must make it disagree
#   8  the page rebuilt from the results, byte for byte, and its numbers matched to the JSON
#   9  sabotages, each proved to have applied AND to have moved the measurement
#  10  hygiene, including the README
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$PWD"
PY=python3

pass=0; fail=0
ok()  { printf '  ok    %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail+1)); }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
SABOTEUR="$ROOT/scripts/_sabotage.py"

# A pristine copy, used by every sabotage so attacks never touch the working tree.
snapshot() {
  local dest="$1"; rm -rf "$dest"; mkdir -p "$dest"
  tar -cf - --exclude=.git --exclude=__pycache__ -C "$ROOT" . | tar -xf - -C "$dest"
}

echo "0. environment"
$PY --version | sed 's/^/        /'
ok "python present"

echo
echo "1. unit suite"
if $PY -m unittest discover -s tests -t . >"$TMP/u.log" 2>&1; then
  NTESTS=$(grep -oE 'Ran [0-9]+ tests' "$TMP/u.log" | grep -oE '[0-9]+')
  ok "$NTESTS unit tests passed"
else
  NTESTS=0
  bad "unit suite"; grep -E 'FAIL:|ERROR:' "$TMP/u.log" | head -12 | sed 's/^/        /'
fi

echo
echo "2. every test has a negative control"
# A suite of assertions that are all satisfied by construction proves nothing. The rule in this
# repo is that each test has a partner ending in _negative_control which breaks something and
# watches the assertion move. This checks the rule held, by parsing the test files rather than
# by trusting the naming to have been applied.
if $PY - <<'PY' >"$TMP/nc.log" 2>&1; then
import ast, pathlib, sys
missing, controls, total = [], 0, 0
for path in sorted(pathlib.Path("tests").glob("test_*.py")):
    tree = ast.parse(path.read_text())
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        names = {f.name for f in cls.body if isinstance(f, ast.FunctionDef)}
        for name in sorted(names):
            if not name.startswith("test_"):
                continue
            total += 1
            if name.endswith("_negative_control"):
                controls += 1
                if name[: -len("_negative_control")] not in names:
                    missing.append(f"{path.name}::{cls.name}::{name} has no positive partner")
            elif name + "_negative_control" not in names:
                missing.append(f"{path.name}::{cls.name}::{name} has no negative control")
if missing:
    sys.exit("tests without a paired control:\n  " + "\n  ".join(missing))
print(f"{total} tests, {controls} of them negative controls, every pair complete")
PY
  sed 's/^/        /' "$TMP/nc.log"; ok "the pairing rule holds"
else bad "$(cat "$TMP/nc.log")"; fi

echo
echo "3. the raw responses are on disk and complete"
if $PY - <<'PY' >"$TMP/raw.log" 2>&1; then
import glob, json, pathlib, sys
from pspread import cli, runner, tasks
analysis_path = pathlib.Path("results/analysis.json")
if not analysis_path.exists():
    sys.exit("results/analysis.json is missing. Run: python3 -m pspread.cli analyze")
analysis = json.loads(analysis_path.read_text())
if not analysis["runs"]:
    sys.exit("results/analysis.json holds no runs, so nothing downstream can be checked")
lines = []
for run in analysis["runs"]:
    task = tasks.get(run["task"])
    _, records = runner.load_done(cli.RAW, task.name, run["model"])
    if not records:
        sys.exit(f"no raw responses on disk for {run['task']} on {run['model']}, so the "
                 f"published numbers cannot be re-derived")
    pairs = {(r["p"], r["i"]) for r in records}
    if len(pairs) != len(records):
        sys.exit(f"{run['task']}/{run['model']}: {len(records) - len(pairs)} duplicate "
                 f"(paraphrase, item) records, which would double count")
    by_pid = {}
    for r in records:
        by_pid.setdefault(r["p"], set()).add(r["i"])
    complete = [p for p, ks in by_pid.items() if len(ks) == len(task.items)]
    partial = len(by_pid) - len(complete)
    # Compared against the PRE-filter count. The equivalence judge removes wordings after the
    # responses are collected, so complete-on-disk is expected to exceed paraphrases_scored,
    # and comparing against the post-filter number made this check fail on a correct pipeline.
    if len(complete) != run["paraphrases_before_equivalence_filter"]:
        sys.exit(f"{run['task']}/{run['model']}: {len(complete)} complete paraphrases on disk, "
                 f"analysis.json counted {run['paraphrases_before_equivalence_filter']} before "
                 f"the equivalence filter")
    if run["paraphrases_scored"] > len(complete):
        sys.exit(f"{run['task']}/{run['model']}: scored {run['paraphrases_scored']} paraphrases "
                 f"from only {len(complete)} complete ones")
    missing_text = sum(1 for r in records if r.get("r") is None)
    lines.append(f"{run['task']:7s} {run['model']:12s} {len(records):6,d} responses, "
                 f"{len(complete)} complete wordings, {run['paraphrases_scored']} of them "
                 f"equivalence-verified, {partial} partial and excluded, "
                 f"{missing_text} failed calls")
print("\n".join(lines))
PY
  sed 's/^/        /' "$TMP/raw.log"; ok "every published number has its raw responses behind it"
else bad "$(cat "$TMP/raw.log")"; fi

echo
echo "4. analysis.json rebuilds from the raw responses"
# Every seed in the analysis is fixed, so a rebuild is deterministic and any difference is a
# real difference. The timestamp is the one field allowed to move.
cp results/analysis.json "$TMP/analysis_committed.json"
if $PY -m pspread.cli analyze >"$TMP/an.log" 2>&1; then
  sed 's/^/        /' "$TMP/an.log" | tail -6
  if $PY - "$TMP/analysis_committed.json" results/analysis.json <<'PY' >"$TMP/cmp.log" 2>&1; then
import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
a.pop("generated_at"); b.pop("generated_at")
if a != b:
    diffs = []
    for ra, rb in zip(a["runs"], b["runs"]):
        for k in ra:
            if ra[k] != rb.get(k):
                diffs.append(f"{ra['task']}/{ra['model']}: field {k} changed")
    sys.exit("the rebuilt analysis differs from the committed one:\n  " +
             "\n  ".join(diffs[:8] or ["structure differs"]))
print("the rebuild is identical to the committed file in every field but the timestamp")
PY
    sed 's/^/        /' "$TMP/cmp.log"; ok "the committed analysis is what the raw data produces"
  else
    bad "$(cat "$TMP/cmp.log")"; cp "$TMP/analysis_committed.json" results/analysis.json
  fi
else bad "analyze failed"; tail -4 "$TMP/an.log" | sed 's/^/        /'; fi

echo
echo "5. the headline numbers re-derived by independent code"
if $PY scripts/check_independent.py >"$TMP/ind.log" 2>&1; then
  sed 's/^/        /' "$TMP/ind.log"; ok "the independent re-derivation agrees exactly"
else
  bad "the independent re-derivation disagrees"; tail -8 "$TMP/ind.log" | sed 's/^/        /'
fi

echo
echo "6. the checker really is independent"
if $PY - <<'PY' >"$TMP/imp.log" 2>&1; then
import ast, pathlib, sys
src = pathlib.Path("scripts/check_independent.py").read_text()
tree = ast.parse(src)
hits = []
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        hits += [a.name for a in n.names if a.name.split(".")[0] == "pspread"]
    elif isinstance(n, ast.ImportFrom):
        if (n.module or "").split(".")[0] == "pspread":
            hits.append(n.module)
    # A dynamic import would defeat a static check, so refuse those outright.
    elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and \
            n.func.id in {"exec", "eval", "__import__", "compile"}:
        hits.append(f"dynamic {n.func.id}()")
    elif isinstance(n, ast.Attribute) and n.attr in {"import_module", "load_module"}:
        hits.append(f"dynamic {n.attr}")
if hits:
    sys.exit(f"check_independent.py can reach the pipeline: {hits}")
if "pspread" in src.replace("`pspread/`", "").replace("pspread.grade", "") and \
        "from pspread" in src:
    sys.exit("check_independent.py imports from pspread")
mods = sorted({n.names[0].name.split(".")[0] for n in ast.walk(tree)
               if isinstance(n, ast.Import)} |
              {(n.module or "").split(".")[0] for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom)})
print(f"imports only {', '.join(mods)}, none of which is pspread, and no dynamic import")
PY
  sed 's/^/        /' "$TMP/imp.log"; ok "no shared code with the pipeline"
else bad "$(cat "$TMP/imp.log")"; fi

echo
echo "7. and the checker fails when the grader is broken"
# The control for layer 5. The first version of this control lowered a threshold on both sides
# at once, which left the two implementations agreeing, and agreement is the thing being
# measured. A control that means something breaks exactly ONE side.
CTL="$TMP/ctl"; snapshot "$CTL"
if $PY - "$CTL/pspread/grade.py" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text()
old = "    pred = cands[-1]"
if old not in t:
    sys.exit("CONTROL SABOTAGE DID NOT APPLY")
p.write_text(t.replace(old, "    pred = cands[0]", 1))
PY
then
  ( cd "$CTL" && $PY -m pspread.cli analyze --permutations 50 --splits 20 ) \
      >"$TMP/ctl-an.log" 2>&1
  if ( cd "$CTL" && $PY scripts/check_independent.py ) >"$TMP/ctl.log" 2>&1; then
    bad "the checker passed against a grader reading the FIRST number instead of the last"
  else
    printf '        %s\n' "$(grep -m1 're-derived as' "$TMP/ctl.log" | cut -c1-96)"
    ok "a broken grader makes the re-derivation disagree, so its agreement means something"
  fi
else bad "the layer 7 control could not be set up, so layer 5 proves nothing"; fi

echo
echo "8. the page is built from the results"
cp docs/index.html "$TMP/page.html" 2>/dev/null || true
if $PY scripts/build_docs.py >"$TMP/d.log" 2>&1; then
  sed 's/^/        /' "$TMP/d.log"
  if [ -f "$TMP/page.html" ] && cmp -s docs/index.html "$TMP/page.html"; then
    ok "docs/index.html is exactly what the results produce"
  elif [ -f "$TMP/page.html" ]; then
    bad "docs/index.html differs from a fresh build"; cp "$TMP/page.html" docs/index.html
  else ok "docs/index.html built (no previous copy to compare against)"; fi
  # A page that rebuilds identically could still be a page with no numbers in it. This asserts
  # the published figures are present in the HTML, computed from the JSON rather than pasted.
  if $PY - <<'PY' >"$TMP/pg.log" 2>&1; then
import json, pathlib, re, sys
page = pathlib.Path("docs/index.html").read_text()
a = json.loads(pathlib.Path("results/analysis.json").read_text())
mult = [r for r in a["runs"] if r["task"] == "mult"]
if not mult:
    sys.exit("no mult run to check the page against")
# Picked by standard deviation. Two models both span the full 0..1 range here, so
# max-by-range is decided by list order rather than by the data.
widest = max(mult, key=lambda r: r["strict"]["sd"])
# Checked on the mean, the standard deviation and the two tail percentiles rather than on the
# min and the max. "0%" is a substring of "100%", so a check on the extremes passes on a page
# that contains only one of them, and a check that cannot fail is not a check.
need = [f"{100 * widest['strict']['mean']:.1f}%", f"{100 * widest['strict']['sd']:.1f}%",
        f"{100 * widest['strict']['p05']:.1f}%", f"{100 * widest['strict']['p95']:.1f}%",
        str(widest["strict"]["n"]), widest["model"]]
absent = [n for n in need if n not in page]
if absent:
    sys.exit(f"the page does not contain {absent}, so it is not showing these results")
if page.count("<polyline") < len(mult):
    sys.exit("the histogram has fewer traces than there are models, so the chart is not drawn")
if "<script" in page:
    sys.exit("the page carries script, which can fail to parse and leave an empty chart")
# Wide content has to scroll inside its own box rather than pushing the page sideways. Hiding
# it with overflow-x on the body would both mask the problem and make any probe for it vacuous,
# so the rule here is that every table sits in a container that scrolls.
if "overflow-x: hidden" in page or "overflow-x:hidden" in page:
    sys.exit("the page hides horizontal overflow, which conceals content rather than fixing it")
loose = len(re.findall(r"<table", page)) - len(re.findall(r"<div class='scroll'><table", page))
if loose:
    sys.exit(f"{loose} table(s) are not inside a scrolling container and will push the page "
             f"sideways on a narrow screen")
if "max-width: 100%" not in page or "viewBox" not in page:
    sys.exit("the SVGs are not set up to scale down, so the charts will overflow on mobile")
bars = page.count("<polyline") + page.count("<rect")
print(f"the page carries mean {need[0]}, sd {need[1]}, 5th-95th {need[2]} to {need[3]} "
      f"over {need[4]} wordings, drawn with {bars} SVG shapes and no JavaScript")
PY
    sed 's/^/        /' "$TMP/pg.log"; ok "the page shows the real numbers"
  else bad "$(cat "$TMP/pg.log")"; fi
else bad "the page could not be built"; tail -3 "$TMP/d.log" | sed 's/^/        /'; fi

echo
echo "9. sabotage"
# Each attack must be proved to have applied, and proved to have MOVED SOMETHING, before a
# failing check counts as the check working. An attack that silently does nothing produces a
# confident write-up about a gap that is not there.
#
# The probe is per attack rather than one shared headline number, because several of these
# attacks cannot move the mult headline at all: that run had zero unparseable responses and zero
# failed calls, so a grader change to either would look like a no-op and the check would report
# a gap that does not exist. Each probe names exactly what its attack is supposed to change.
#
# Catching is then either the unit suite, or the independent re-derivation run against an
# analysis rebuilt BY THE SABOTAGED CODE. That rebuild is what makes the second route work: the
# checker shares no code with the pipeline, so it can only notice a sabotage once the sabotaged
# pipeline has written its answer down.
attack() {
  local name="$1" file="$2" old="$3" new="$4" probe="$5"
  local dir="$TMP/a-$name"; snapshot "$dir"
  if ! $PY "$SABOTEUR" "$dir/$file" "$old" "$new"; then
    bad "sabotage \"$name\" did not apply, so it proves nothing"; return
  fi

  local before after urc irc
  before="$( $PY -c "$probe" 2>&1 | tail -1 )"
  after="$( cd "$dir" && $PY -c "$probe" 2>&1 | tail -1 )"
  if [ "$before" = "$after" ]; then
    bad "sabotage \"$name\" applied but its probe still reports $before, so it is a no-op"
    return
  fi
  set +e
  ( cd "$dir" && $PY -m unittest discover -s tests -t . ) >"$TMP/$name-u.log" 2>&1; urc=$?
  ( cd "$dir" && $PY -m pspread.cli analyze --permutations 40 --splits 20 ) \
      >"$TMP/$name-a.log" 2>&1
  ( cd "$dir" && $PY scripts/check_independent.py ) >"$TMP/$name-i.log" 2>&1; irc=$?
  set -e
  printf '        %-30s %s -> %s\n' "$name" "$before" "$after"
  if [ "$urc" -ne 0 ] || [ "$irc" -ne 0 ]; then
    ok "sabotage \"$name\" moved its probe and was caught (unit $urc, independent $irc)"
  else
    bad "sabotage \"$name\" moved its probe and nothing noticed"
  fi
}

G='import sys; sys.path.insert(0, "."); from pspread import grade, stats'

# The grader reads the wrong end of the response.
attack "grader-reads-first-number" "pspread/grade.py" \
  "    pred = cands[-1]" "    pred = cands[0]" \
  "$G; print(grade.grade_one('47 x 83 = 3901', '3901', 'integer')[0])"
# Unparseable folded into wrong, which is the silent-failure pattern this project is about.
attack "unparseable-scored-as-wrong" "pspread/grade.py" \
  "        return UNPARSEABLE, False, None" "        return WRONG, False, None" \
  "$G; print(grade.grade_group([('a', 'no digits here')], {'a': '1'}, 'integer')['unparseable'])"
# A failed call scored as a wrong answer, which would let a flaky server look like a bad wording.
attack "failed-call-scored-as-wrong" "pspread/grade.py" \
  "        return ERROR, False, None" "        return WRONG, False, None" \
  "$G; print(grade.grade_group([('a', None)], {'a': '1'}, 'integer')['error'])"
# Substring matching, the version of the label rule that fires on the word "not".
attack "lenient-substring-matching" "pspread/grade.py" \
  '_LABEL = re.compile(r"(?<![0-9A-Za-z_])(yes|no|unknown)(?![0-9A-Za-z_])")' \
  '_LABEL = re.compile(r"(yes|no|unknown)")' \
  "$G; print(grade.candidates('it is not the case', 'label'))"
# The spread itself: a sample standard deviation inflates it.
attack "sample-sd-inflates-the-spread" "pspread/stats.py" \
  "    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))" \
  "    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))" \
  "$G; print(round(stats.stdev([0.0, 1.0]), 6))"
# Cochran's Q with the wrong leading constant. The unit suite cannot see this one, because the
# permutation null uses the same formula and the p-value comes out unchanged. Only the
# independent re-derivation of Q catches it, which is the reason that layer exists.
attack "cochran-q-wrong-constant" "pspread/stats.py" \
  "    num = k * (k - 1) * sum((g - gbar) ** 2 for g in col_totals)" \
  "    num = k * sum((g - gbar) ** 2 for g in col_totals)" \
  "$G; print(round(stats.cochran_q([[1,1,1,1]]*2 + [[0,0,0,0]]*2), 6))"
# A p-value that is always 1 reports "no spread found" whatever the data says.
attack "p-value-always-one" "pspread/stats.py" \
  "    ge = sum(1 for v in null_values if v >= observed)
    return (ge + 1) / (len(null_values) + 1)" \
  "    return 1.0" \
  "$G; print(round(stats._upper_p(9.0, [1.0, 2.0, 3.0]), 6))"
# A reliability that is always perfect would make item-set luck look like a real effect.
attack "reliability-always-perfect" "pspread/stats.py" \
  '        "spearman_brown": mean(c for c in corrected if c == c),' \
  '        "spearman_brown": 1.0,' \
  "$G; import random; rng = random.Random(1);
rows = [[1 if rng.random() < d else 0 for d in [0.2,0.5,0.8,0.4,0.6,0.3]] for _ in range(40)];
print(round(stats.split_half_reliability(rows, reps=20, seed=2)['spearman_brown'], 6))"

echo "10. hygiene"
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  hits=$(git -C "$ROOT" grep -In -e "/home/$(id -un)" -- . 2>/dev/null \
         | grep -vE '^(scripts/verify\.sh|README\.md)' || true)
  if [ -z "$hits" ]; then ok "no absolute home paths in tracked files"
  else bad "home paths"; printf '%s\n' "$hits" | head -4 | sed 's/^/        /'; fi
  keys=$(git -C "$ROOT" grep -In -E 'sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{36}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}' \
         -- . 2>/dev/null || true)
  if [ -z "$keys" ]; then ok "no credential-shaped strings"
  else bad "possible credential"; printf '%s\n' "$keys" | head -3 | sed 's/^/        /'; fi
  big=$(git -C "$ROOT" ls-files | while read -r f; do
          [ -f "$f" ] && [ "$(stat -c%s "$f")" -gt 800000 ] && echo "$f"; done || true)
  if [ -z "$big" ]; then ok "no tracked file over 800 KB"
  else bad "large files"; printf '%s\n' "$big" | head -3 | sed 's/^/        /'; fi
  # One NUL byte makes git and grep treat a file as binary, and the two scans above then skip
  # it entirely while reporting the same clean result.
  if $PY - "$ROOT" <<'PY' >"$TMP/nul.log" 2>&1; then
import os, subprocess, sys
root = sys.argv[1]
files = [f.decode() for f in subprocess.run(["git", "-C", root, "ls-files", "-z"],
                                            capture_output=True, check=True).stdout.split(b"\0") if f]
bad = [f for f in files if os.path.isfile(os.path.join(root, f))
       and b"\0" in open(os.path.join(root, f), "rb").read()]
if bad:
    sys.exit("files containing NUL, which the secret scan cannot read: " + ", ".join(bad))
print(f"{len(files)} tracked files, none contain NUL")
PY
    sed 's/^/        /' "$TMP/nul.log"; ok "no tracked file is binary to the secret scan"
  else bad "$(cat "$TMP/nul.log")"; fi
else bad "not a git repo"; fi

# The README is a claim like any other. A project can report every check green while its README
# still says TODO, and that has happened in this workspace.
if [ -f README.md ]; then
  if grep -q "^## Status" README.md; then
    if grep -q "VERIFY OK" README.md; then ok "README has a Status section with a real result"
    else bad "README Status section does not contain the verify success line"; fi
  else bad "README has no ## Status section"; fi
  # Searched outside fenced code blocks only. The Status section pastes this script's own
  # output, which includes the line reporting that no TODO is left, so a plain grep matches its
  # own success message and the check fails on a correct README. Found the hard way.
  if $PY - <<'PY' >"$TMP/todo.log" 2>&1; then
import pathlib, re, sys
text = pathlib.Path("README.md").read_text()
prose = re.sub(r"```.*?```", "", text, flags=re.S)
hits = [ln.strip() for ln in prose.splitlines() if "TODO" in ln]
if hits:
    sys.exit("README prose still contains TODO: " + hits[0][:80])
fenced = len(re.findall(r"```", text)) // 2
print(f"no TODO in the README prose, outside {fenced} fenced block(s)")
PY
    sed 's/^/        /' "$TMP/todo.log"; ok "README has no TODO left in it"
  else bad "$(cat "$TMP/todo.log")"; fi
  # The counts in the README go stale the moment a test is added, so they are asserted here.
  if [ "$NTESTS" -gt 0 ] && grep -qE "\*\*$NTESTS\*\* unit tests" README.md; then
    ok "the README's test count still matches the suite ($NTESTS)"
  else
    bad "the README does not claim exactly $NTESTS unit tests"
  fi
  if $PY - <<'PY' >"$TMP/rm.log" 2>&1; then
import json, pathlib, re, sys
readme = pathlib.Path("README.md").read_text()
a = json.loads(pathlib.Path("results/analysis.json").read_text())
mult = [r for r in a["runs"] if r["task"] == "mult"]
# Picked by standard deviation. Two models both span the full 0..1 range here, so
# max-by-range is decided by list order rather than by the data.
widest = max(mult, key=lambda r: r["strict"]["sd"])
n = widest["strict"]["n"]
# The guard is on the lede, everything before the first section heading, because that is where
# a reader takes the headline number from. Naming 1,000 there is legal only when the same
# sentence disclaims it: "not 1,000", "rather than 1,000". Anything else is the overclaim this
# check exists to stop. Cutting the lede at a fixed character count was the first version and
# it passed or failed on where a line wrapped, which is not a property of the claim.
lede = readme.split("\n## ", 1)[0]
if str(n) not in lede:
    sys.exit(f"the README lede does not state the real number of wordings ({n})")
if n < 1000:
    for m in re.finditer(r"\b1,?000\b", lede):
        before = lede[max(0, m.start() - 40):m.start()].lower()
        if not re.search(r"\b(not|rather than|instead of|asked for|short of)\b\s*$", before):
            sys.exit(f"the README lede claims 1,000 while only {n} wordings were run, at: "
                     f"...{lede[max(0, m.start() - 60):m.end() + 20]}...")
# Same reason as on the page: the extremes are not distinguishable as substrings, so the
# README is pinned to figures that are.
need = {"paraphrase count": str(n),
        "mean accuracy": f"{100 * widest['strict']['mean']:.1f}%",
        "standard deviation": f"{100 * widest['strict']['sd']:.1f}%",
        "5th percentile": f"{100 * widest['strict']['p05']:.1f}%",
        "95th percentile": f"{100 * widest['strict']['p95']:.1f}%",
        "null range under the permutation test":
            f"{100 * widest['spread_test']['null_range_mean']:.1f}%",
        "split-half reliability": f"{widest['reliability']['spearman_brown']:.2f}"}
absent = [k for k, v in need.items() if v not in readme]
if absent:
    sys.exit(f"the README is missing its own headline figures: {absent} "
             f"(expected {need})")
print(f"the README states {n} wordings, mean {need['mean accuracy']}, sd "
      f"{need['standard deviation']}, and the permutation null's own range, all matching "
      f"results/analysis.json")
PY
    sed 's/^/        /' "$TMP/rm.log"; ok "the README's headline numbers match the results"
  else bad "$(cat "$TMP/rm.log")"; fi
else bad "no README.md"; fi

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || { echo "VERIFY FAILED"; exit 1; }
echo "VERIFY OK"
