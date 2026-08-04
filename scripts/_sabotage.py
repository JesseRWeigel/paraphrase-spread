#!/usr/bin/env python3
"""Apply one exact string replacement to a file, or exit nonzero saying why it could not.

Used only by `scripts/verify.sh`, which breaks the code on purpose in a throwaway copy and then
checks that something notices. It exists as its own file so the failure modes are explicit:

  the target text is absent   the attack did not apply, and any conclusion drawn from the
                              "passing" verify afterwards would be about nothing
  old and new are identical   the attack is a no-op wearing an attack's name

Both exit 1. A silent success here is the worst outcome available, because it produces a
confident report that a check has a gap when the check is fine.
"""

import pathlib
import sys


def main():
    if len(sys.argv) != 4:
        print("usage: _sabotage.py <file> <old> <new>", file=sys.stderr)
        return 2
    path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
    p = pathlib.Path(path)
    if not p.exists():
        print(f"SABOTAGE TARGET MISSING: {path}", file=sys.stderr)
        return 1
    text = p.read_text()
    if old not in text:
        print(f"SABOTAGE DID NOT APPLY: {old!r} is absent from {path}", file=sys.stderr)
        return 1
    if old == new:
        print("SABOTAGE IS A NO-OP: old and new text are identical", file=sys.stderr)
        return 1
    p.write_text(text.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
