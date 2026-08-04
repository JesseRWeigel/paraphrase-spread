"""Answer extraction and grading.

The extraction rules are written out in prose below because `scripts/check_independent.py`
reimplements them from this specification without importing anything from this package. Two
independent implementations of a precise spec should agree exactly, and the verify script
requires exactly that, so a change to one side that is not a change to the spec shows up as a
disagreement rather than as a quietly different number.

INTEGER EXTRACTION (task `mult`)
  1. Delete every comma that has an ASCII digit immediately before and after it.
  2. Collect every maximal run of ASCII digits, in order of appearance.
  3. If there are none, the response is UNPARSEABLE.
  4. The strict prediction is the LAST run, compared as an integer.
  5. The lenient verdict is CORRECT if ANY run equals the answer as an integer.

LABEL EXTRACTION (task `entail`)
  1. Lowercase the response.
  2. Collect every whole-word occurrence of `yes`, `no`, or `unknown`, in order of appearance.
     Whole word means the neighbouring characters are not ASCII letters, digits, or underscore,
     so `not` does not contain `no` and `unknowable` does not contain `unknown`.
  3. If there are none, the response is UNPARSEABLE.
  4. The strict prediction is the LAST occurrence.
  5. The lenient verdict is CORRECT if ANY occurrence equals the answer.

UNPARSEABLE IS ITS OWN OUTCOME.
  A response that carries no candidate answer is counted in `unparseable` and is NOT counted in
  `correct`. Both accuracy definitions are reported: `strict_accuracy` divides by every attempt,
  which is what a benchmark harness reports, and `parsed_accuracy` divides by the attempts that
  produced a candidate answer. They differ exactly when a wording makes the model refuse to
  answer in a recoverable form, which is itself one of the effects this project measures.
"""

import re

_COMMA_IN_NUMBER = re.compile(r"(?<=[0-9]),(?=[0-9])")
_DIGIT_RUN = re.compile(r"[0-9]+")
_LABEL = re.compile(r"(?<![0-9A-Za-z_])(yes|no|unknown)(?![0-9A-Za-z_])")

CORRECT = "correct"
WRONG = "wrong"
UNPARSEABLE = "unparseable"
ERROR = "error"


def candidates(text, answer_kind):
    """Every candidate answer in `text`, in order of appearance."""
    if answer_kind == "integer":
        return _DIGIT_RUN.findall(_COMMA_IN_NUMBER.sub("", text))
    if answer_kind == "label":
        return _LABEL.findall(text.lower())
    raise ValueError(f"unknown answer_kind {answer_kind!r}")


def _same(a, b, answer_kind):
    if answer_kind == "integer":
        return int(a) == int(b)
    return a == b


def grade_one(text, answer, answer_kind):
    """Return (strict_outcome, lenient_correct, prediction_or_None).

    `text` of None means the model call itself failed, which is ERROR and is never silently
    folded into WRONG. A failed call is missing data, and missing data that looks like a wrong
    answer would drag a paraphrase's score down for a reason that has nothing to do with wording.
    """
    if text is None:
        return ERROR, False, None
    cands = candidates(text, answer_kind)
    if not cands:
        return UNPARSEABLE, False, None
    pred = cands[-1]
    lenient = any(_same(c, answer, answer_kind) for c in cands)
    strict = CORRECT if _same(pred, answer, answer_kind) else WRONG
    return strict, lenient, pred


def grade_group(records, answers, answer_kind):
    """Grade every response for one paraphrase.

    `records` is an iterable of (item_key, response_text_or_None). `answers` maps item key to
    the correct answer. Returns a dict whose counts always sum to the number of attempts.
    """
    counts = {CORRECT: 0, WRONG: 0, UNPARSEABLE: 0, ERROR: 0}
    lenient_correct = 0
    per_item = {}
    for key, text in records:
        strict, lenient, _ = grade_one(text, answers[key], answer_kind)
        counts[strict] += 1
        lenient_correct += int(lenient)
        per_item[key] = 1 if strict == CORRECT else 0
    attempts = sum(counts.values())
    scored = attempts - counts[ERROR]
    parsed = counts[CORRECT] + counts[WRONG]
    return {
        "attempts": attempts,
        "correct": counts[CORRECT],
        "wrong": counts[WRONG],
        "unparseable": counts[UNPARSEABLE],
        "error": counts[ERROR],
        "lenient_correct": lenient_correct,
        # Strict accuracy counts an unparseable response against the wording, because a harness
        # scoring this run would. Errored calls are excluded from the denominator entirely.
        "strict_accuracy": counts[CORRECT] / scored if scored else None,
        "parsed_accuracy": counts[CORRECT] / parsed if parsed else None,
        "lenient_accuracy": lenient_correct / scored if scored else None,
        "per_item": per_item,
    }
