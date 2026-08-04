"""Surface features of a prompt template, for asking which ones track accuracy.

These are shallow on purpose. Every one is a property a person could read off the prompt in a
second, because the useful version of "which wordings work" is one you can apply while writing a
prompt, not one that needs an embedding model to evaluate.

They are also correlational and mostly not independent of each other. Length correlates with
almost everything, so a feature that survives only because long prompts also tend to carry a
format instruction is not a finding. The analysis reports each feature's correlation with
accuracy after Holm correction across the whole set, and the README says plainly that these are
associations within one generator's output.
"""

import re

_THINK = re.compile(
    r"step[- ]by[- ]step|think (carefully|it through|about)|take your time|reason(ing)? "
    r"through|work through|consider carefully|be careful|careful(ly)? (about|to)", re.I)
_IMMEDIATE = re.compile(
    r"immediately|without (any )?(explanation|elaborat|comment|preamble|working)|no "
    r"(explanation|elaboration|commentary|working|preamble)|do ?n[o']?t explain|straight "
    r"away|right away|at once", re.I)
_FORMAT = re.compile(
    r"nothing else|no other text|only the|just the|plain (integer|number)|bare|solely|and "
    r"nothing|single (integer|number|word)|one of those|exactly one word", re.I)
_POLITE = re.compile(
    r"\bplease\b|thank you|thanks|if you (can|could|would)|kindly|when you get a chance|"
    r"would you|could you|i'd appreciate|appreciate it|no rush", re.I)
_ROLE = re.compile(r"^(you are|as an?|imagine you|act as|assume the role)", re.I)
_MARKDOWN = re.compile(r"\*\*|`|^#{1,6} |\*[A-Za-z]")
_LIST = re.compile(r"\b1[.)]\s|\bstep 1\b|\bfirst,|\(1\)", re.I)
_CAPS = re.compile(r"\b[A-Z]{3,}\b")
_SLOT = re.compile(r"\{[a-z_]+\}")

# Name, description, and how to compute it. Order is the reporting order.
SPECS = [
    ("chars", "template length in characters", lambda t: float(len(t))),
    ("words", "template length in whitespace words", lambda t: float(len(t.split()))),
    ("sentences", "count of . ? or ! followed by a space or end",
     lambda t: float(len(re.findall(r"[.?!](\s|$)", t)))),
    ("is_question", "contains a question mark", lambda t: float("?" in t)),
    ("role_frame", "opens with a role assignment", lambda t: float(bool(_ROLE.match(t.strip())))),
    ("think_cue", "invites deliberation before answering",
     lambda t: float(bool(_THINK.search(t)))),
    ("immediate_cue", "demands an answer with no working",
     lambda t: float(bool(_IMMEDIATE.search(t)))),
    ("format_instruction", "states the output must be the answer alone",
     lambda t: float(bool(_FORMAT.search(t)))),
    ("politeness", "contains a politeness or hedging marker",
     lambda t: float(bool(_POLITE.search(t)))),
    ("markdown", "uses markdown emphasis or code marks",
     lambda t: float(bool(_MARKDOWN.search(t)))),
    ("numbered_list", "structured as numbered steps", lambda t: float(bool(_LIST.search(t)))),
    ("shouty_caps", "two or more all-caps words of 3+ letters",
     lambda t: float(len(_CAPS.findall(t)) >= 2)),
    ("slot_position", "where the first placeholder sits, 0 at the start and 1 at the end",
     lambda t: (_SLOT.search(t).start() / len(t)) if _SLOT.search(t) and t else 0.0),
    ("format_before_slot", "the output-format requirement precedes the problem",
     lambda t: float(bool(_FORMAT.search(t)) and bool(_SLOT.search(t))
                     and _FORMAT.search(t).start() < _SLOT.search(t).start())),
]

NAMES = [s[0] for s in SPECS]
DESCRIPTIONS = {name: desc for name, desc, _ in SPECS}


def extract(template):
    return {name: fn(template) for name, _, fn in SPECS}
