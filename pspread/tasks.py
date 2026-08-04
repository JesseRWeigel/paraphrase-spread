"""The fixed tasks.

Every item's ground truth is computed here, not typed in by hand, so there is no chance of a
transcription error in the answer key. Both tasks are deterministic functions of an integer
seed, so the item set is reproducible from the code alone.

A task supplies:
  items()      a list of Item(slots, answer), where slots fill a prompt template
  canonical    the reference wording, which every paraphrase must preserve the meaning of
  answer_kind  what the grader is looking for: "integer" or one of a fixed label set
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    slots: dict
    answer: str


@dataclass(frozen=True)
class Task:
    name: str
    canonical: str
    answer_kind: str
    labels: tuple
    slot_names: tuple
    items: tuple
    blurb: str


def _mult_items(n=24, seed=20260803):
    """Two-digit by two-digit multiplication.

    Both factors are drawn from 12..97 and rejected if either ends in 0 or 1, or if the two
    are equal. Those cases are much easier than the rest and would compress the accuracy range
    for reasons that have nothing to do with wording.
    """
    rng = random.Random(seed)
    out, seen = [], set()
    while len(out) < n:
        a, b = rng.randint(12, 97), rng.randint(12, 97)
        if a % 10 in (0, 1) or b % 10 in (0, 1) or a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        out.append(Item(f"mult-{a}x{b}", {"a": str(a), "b": str(b)}, str(a * b)))
    return tuple(out)


# Four conditional argument forms are built below. Two are valid, two are formal fallacies, and
# the fallacies are the reason this task is not trivial: a model that pattern-matches "if/then"
# without tracking direction answers YES to affirming the consequent.
_CONTENT = [
    ("the valve is open", "the tank is draining"),
    ("the badge is blue", "the holder works nights"),
    ("the seed was soaked", "the sprout appeared"),
    ("the ledger balances", "the audit closed"),
    ("the relay clicked", "the lamp is lit"),
    ("the crate is sealed", "the label is stamped"),
]


def _entail_items(n=24):
    """Conditional reasoning, three-way.

    Each item states a rule "if P then Q", gives one extra fact, and asks about a target
    proposition. The answer is YES if the target follows, NO if its negation follows, and
    UNKNOWN if neither does. Content is deliberately arbitrary so world knowledge cannot
    substitute for the inference.

    The UNKNOWN convention is stated in the canonical prompt and every paraphrase has to carry
    it, otherwise the item has no determinate answer.
    """
    out = []
    for p, q in _CONTENT:
        out.append(Item(f"mp-{len(out)}", {
            "rule": f"If {p}, then {q}.", "fact": f"{p.capitalize()}.",
            "target": f"{q.capitalize()}"}, "yes"))
        out.append(Item(f"mt-{len(out)}", {
            "rule": f"If {p}, then {q}.", "fact": f"It is not the case that {q}.",
            "target": f"{p.capitalize()}"}, "no"))
        out.append(Item(f"ac-{len(out)}", {
            "rule": f"If {p}, then {q}.", "fact": f"{q.capitalize()}.",
            "target": f"{p.capitalize()}"}, "unknown"))
        out.append(Item(f"da-{len(out)}", {
            "rule": f"If {p}, then {q}.", "fact": f"It is not the case that {p}.",
            "target": f"{q.capitalize()}"}, "unknown"))
    return tuple(out[:n])


MULT = Task(
    name="mult",
    canonical="Compute the product of {a} and {b}. Give the final answer as a plain integer "
              "with no commas and no other text.",
    answer_kind="integer",
    labels=(),
    slot_names=("a", "b"),
    items=_mult_items(),
    blurb="Two-digit by two-digit multiplication, 24 items, answer key computed in code.",
)

ENTAIL = Task(
    name="entail",
    canonical="{rule} {fact}\n\nDoes it follow that: {target}? Answer YES if it follows, NO if "
              "its negation follows, and UNKNOWN if neither can be determined. Answer with one "
              "of those three words and nothing else.",
    answer_kind="label",
    labels=("yes", "no", "unknown"),
    slot_names=("rule", "fact", "target"),
    items=_entail_items(),
    blurb="Conditional reasoning with two valid forms and two formal fallacies, 24 items.",
)

TASKS = {t.name: t for t in (MULT, ENTAIL)}


def get(name):
    if name not in TASKS:
        raise KeyError(f"unknown task {name!r}, have {sorted(TASKS)}")
    return TASKS[name]
