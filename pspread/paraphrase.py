"""Generate and validate prompt paraphrases.

A paraphrase here is a whole prompt template with the item's slots left empty, so the thing that
varies between runs is the wording of the instruction and nothing about the problem itself. The
same 24 items go through every template.

WHERE THE PARAPHRASES COME FROM, AND WHY THAT MATTERS.
They are written by one model, Gemini 3 Flash, under style directives chosen by the author. That
is not a random sample of the phrasings a person might use, and no sample of model output can be.
It is a sample from one generator conditioned on one list of styles, and every number downstream
inherits that. The generation prompt and the style list are in this file so the bias is
inspectable rather than described.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GENERATOR_MODEL = "gemini-3-flash-preview"

# Fourteen directives. Diversity in the pool comes mostly from these, so they are part of the
# measurement rather than an implementation detail, and a different list would give a different
# spread. Nothing here tells the model to be worse at the task.
STYLES = [
    "terse and imperative, as short as you can make it while keeping every requirement",
    "polite and slightly formal, the way a person asks a colleague for a favour",
    "phrased as a direct question rather than a command",
    "with a short role frame at the start, for example 'You are a careful assistant.'",
    "wordy and over-explained, at least three sentences",
    "in a dry technical register, like a specification",
    "casual and conversational, contractions allowed",
    "with the output-format requirement stated first, before the problem",
    "as a numbered list of instructions",
    "using light markdown, such as bold on the key requirement",
    "with an explicit invitation to think carefully before answering",
    "with an explicit instruction to answer immediately without explanation",
    "framed as a line from a larger worksheet or exam paper",
    "with mild hedging, for example 'if you can' or 'when you get a chance'",
]

# A second diversity axis. One style directive on its own runs dry after a handful of wordings,
# which is why the first attempt at this returned nine lines when it was asked for forty. Crossing
# style with structure gives the generator somewhere new to go on each call.
AXES = [
    "vary the opening word, and do not start with the same verb twice",
    "avoid the word 'product' entirely",
    "put the two quantities at the very end of the wording",
    "put the two quantities at the very start of the wording",
    "keep it to exactly one sentence",
    "use at least three sentences",
    "refer to the reader in the third person, or to nobody at all",
    "give a brief reason why the output format matters",
    "use a rhetorical framing, such as a challenge or an invitation",
    "write it the way it would appear inside a longer document",
]

_PROMPT = """You are producing test material for a study of how much a language model's accuracy
depends on prompt wording. I need many DIFFERENT wordings of ONE fixed instruction.

The reference instruction is, exactly:

{canonical}

Write {n} alternative wordings of that instruction. Every one must be {style}. Also, {axis}.

Hard requirements for every line you write:
- It must contain each of these placeholders exactly once, spelled exactly like this: {slots}
- It must ask for exactly the same thing as the reference, no more and no less.
- {extra}
- It must not answer the question, give an example answer, or contain any worked example.
- It must be a single line with no line breaks, no numbering, and no bullet or quote marks.
{avoid}
Output {n} lines, one wording per line, and nothing else.
"""

_AVOID = """
These wordings already exist. Yours must be clearly different from all of them:
{lines}
"""

_EXTRA = {
    "mult": "It must still ask for a single final numeric answer that stands alone, so the "
            "answer can be read off without interpretation.",
    "entail": "It must still offer exactly the three answer options and must use the three "
              "literal words YES, NO and UNKNOWN as the option names, because the grader looks "
              "for those words.",
}


def _post(url, payload, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def call_generator(prompt, model=GENERATOR_MODEL, temperature=1.0, retries=4):
    """One call to the paraphrase generator. Raises if the key is absent."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Paraphrase generation needs it. The rest of the "
            "pipeline does not: results/paraphrases_*.json is committed, so analysis and "
            "verification run without any API access.")
    url = f"{GEMINI_BASE}/{model}:generateContent?key={key}"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096}}
    last = None
    for attempt in range(retries):
        try:
            d = _post(url, body)
            cand = d["candidates"][0]
            return "".join(p.get("text", "") for p in cand["content"]["parts"])
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"paraphrase generator failed after {retries} attempts: {last}")


# --- validation -------------------------------------------------------------------------

_BRACE = re.compile(r"\{[^}]*\}")
_LONG_NUMBER = re.compile(r"[0-9]{3,}")


def validate(text, task):
    """Return None if the template is usable, otherwise the reason it is not.

    A rejected candidate is recorded with its reason rather than dropped silently, because the
    rejection rate is part of the honest description of where the pool came from.
    """
    t = text.strip()
    if not t:
        return "empty"
    if "\n" in t:
        return "multiline"
    if not (20 <= len(t) <= 700):
        return f"length {len(t)} outside 20..700"
    found = _BRACE.findall(t)
    want = ["{" + s + "}" for s in task.slot_names]
    for slot in want:
        if found.count(slot) != 1:
            return f"placeholder {slot} appears {found.count(slot)} times"
    extra = [f for f in found if f not in want]
    if extra:
        return f"unexpected placeholder(s) {extra}"
    if task.name == "mult" and _LONG_NUMBER.search(t):
        return "contains a 3+ digit number, which could be a leaked answer"
    if task.name == "entail":
        low = t.lower()
        for word in ("yes", "no", "unknown"):
            if not re.search(rf"(?<![0-9a-z_]){word}(?![0-9a-z_])", low):
                return f"does not name the option {word!r}"
    return None


def normalise(text):
    """The key used for exact-duplicate detection: lowercase, punctuation-free, whitespace-flat."""
    t = re.sub(r"[^a-z0-9{} ]+", " ", text.lower())
    return " ".join(t.split())


def dedupe(candidates):
    """Drop exact duplicates after normalisation, keeping first occurrence.

    Near-duplicates are deliberately kept. A generator really does produce clusters of very
    similar wordings, and thinning them out would make the pool look more diverse than the
    thing that produced it.
    """
    seen, out, dropped = set(), [], 0
    for c in candidates:
        k = normalise(c)
        if k in seen:
            dropped += 1
            continue
        seen.add(k)
        out.append(c)
    return out, dropped


def build_prompt(task, style, n, axis="write them however you like", avoid=()):
    return _PROMPT.format(
        canonical=task.canonical.replace("\n\n", " "), n=n, style=style, axis=axis,
        slots=", ".join("{" + s + "}" for s in task.slot_names),
        extra=_EXTRA[task.name],
        avoid=_AVOID.format(lines="\n".join(avoid)) if avoid else "")
