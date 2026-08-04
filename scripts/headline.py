#!/usr/bin/env python3
"""Print the headline numbers for one run, straight from the raw responses.

This is a probe, not a check. It exists so `scripts/verify.sh` can compare the measurement a
sabotaged copy of the code produces against the measurement the real code produces, and fail if
a sabotage turned out to be a no-op. It deliberately DOES import `pspread`, because the whole
point is to observe what the code under attack now reports.

The permutation tests are skipped so this runs in about a second.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pspread import cli, grade, runner, stats, tasks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="mult")
    ap.add_argument("--model", default="qwen3:8b")
    args = ap.parse_args()

    task = tasks.get(args.task)
    answers = {i.key: i.answer for i in task.items}
    item_keys = [i.key for i in task.items]
    _, records = runner.load_done(cli.RAW, task.name, args.model)
    if not records:
        print(f"no raw responses for {args.task} on {args.model}", file=sys.stderr)
        return 2

    by_pid = {}
    for r in records:
        by_pid.setdefault(r["p"], []).append((r["i"], r.get("r")))

    accs, rows, counts = [], [], {"correct": 0, "wrong": 0, "unparseable": 0, "error": 0}
    for pid, recs in sorted(by_pid.items()):
        if len(recs) < len(item_keys):
            continue
        g = grade.grade_group(recs, answers, task.answer_kind)
        for key in counts:
            counts[key] += g[key]
        accs.append(g["strict_accuracy"])
        rows.append([g["per_item"][k] for k in item_keys])

    q = stats.cochran_q(rows)
    print(f"n={len(accs)} mean={stats.mean(accs):.6f} sd={stats.stdev(accs):.6f} "
          f"min={min(accs):.6f} max={max(accs):.6f} q={q if q is None else round(q, 4)} "
          f"correct={counts['correct']} wrong={counts['wrong']} "
          f"unparseable={counts['unparseable']} error={counts['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
