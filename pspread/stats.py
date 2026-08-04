"""Distribution statistics, and the tests that decide whether the spread means anything.

WHY THE OBVIOUS ERROR BAR IS THE WRONG ONE.
Every call runs at temperature 0 with a fixed seed, so a paraphrase's accuracy on these 24 items
is not a noisy estimate of anything. It is that paraphrase's exact score on that item set. The
uncertainty that matters is different: would the same paraphrase still look good on a DIFFERENT
24 items, or did it just happen to suit these ones?

Two tests answer that, and they answer it in different ways on purpose.

COCHRAN'S Q asks whether the paraphrases differ at all. Its null is that within any one item,
which paraphrases got it right is arbitrary, so all the structure in the matrix comes from some
items being harder than others. The null distribution is built by permuting the correct/incorrect
labels within each item row, which is exact under that null and needs no chi-squared table.

SPLIT-HALF RELIABILITY asks whether a paraphrase's advantage carries to items it was not measured
on. Score every paraphrase on a random half of the items and again on the other half, correlate
the two across paraphrases, and correct for the halving with Spearman-Brown. A spread that is
pure item-set luck gives a reliability near zero however large the range looks.

A large range with a reliability of zero would be a real result and the opposite of the one
claimed here, so both numbers are reported whatever they come out as.
"""

import math
import random


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def stdev(xs):
    """Population standard deviation. These are all the paraphrases in the pool, not a sample
    drawn from it, so there is no n-1 correction to make."""
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def percentile(xs, q):
    """Linear interpolation between order statistics, the same convention as numpy's default."""
    xs = sorted(xs)
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[int(pos)]
    return xs[lo] * (hi - pos) + xs[hi] * (pos - lo)


def histogram(xs, lo=0.0, hi=1.0, bins=20):
    edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for x in xs:
        idx = int((x - lo) / (hi - lo) * bins)
        idx = min(max(idx, 0), bins - 1)
        counts[idx] += 1
    return {"edges": edges, "counts": counts}


def describe(xs):
    xs = list(xs)
    if not xs:
        # An empty input is "could not measure", which is a different fact from a measurement
        # of zero, and collapsing the two is the silent-failure pattern.
        return {"n": 0, "mean": None, "sd": None, "min": None, "max": None, "range": None,
                "p05": None, "p25": None, "median": None, "p75": None, "p95": None,
                "iqr": None}
    return {
        "n": len(xs),
        "mean": mean(xs),
        "sd": stdev(xs),
        "min": min(xs) if xs else None,
        "max": max(xs) if xs else None,
        "range": (max(xs) - min(xs)) if xs else None,
        "p05": percentile(xs, 0.05),
        "p25": percentile(xs, 0.25),
        "median": percentile(xs, 0.50),
        "p75": percentile(xs, 0.75),
        "p95": percentile(xs, 0.95),
        "iqr": percentile(xs, 0.75) - percentile(xs, 0.25),
    }


# --- the matrix -------------------------------------------------------------------------

def to_matrix(per_paraphrase, item_keys):
    """rows = paraphrases, columns = items, cells 1 correct / 0 not.

    Only paraphrases with a complete row are used, so no cell is imputed and no paraphrase is
    compared to another on a different set of items.
    """
    rows, ids = [], []
    for pid, per_item in per_paraphrase:
        if any(k not in per_item for k in item_keys):
            continue
        rows.append([per_item[k] for k in item_keys])
        ids.append(pid)
    return ids, rows


def cochran_q(rows):
    """Q for k related binary treatments over b blocks.

    `rows` is paraphrase-major, so it is transposed here: Cochran's blocks are the items.
    """
    k = len(rows)
    if k < 2:
        return None
    b = len(rows[0])
    col_totals = [sum(r) for r in rows]              # per paraphrase, over items
    row_totals = [sum(rows[j][i] for j in range(k)) for i in range(b)]  # per item
    gbar = sum(col_totals) / k
    num = k * (k - 1) * sum((g - gbar) ** 2 for g in col_totals)
    den = k * sum(row_totals) - sum(l * l for l in row_totals)
    if den == 0:
        return None      # every item answered identically by every paraphrase
    return num / den


def permutation_null(rows, reps=1000, seed=11):
    """Null distribution of Q and of the accuracy spread, by permuting within each item.

    Each item keeps its own difficulty exactly: if 137 of 400 paraphrases got item 5 right, then
    in every permuted matrix exactly 137 do, and only WHICH ones changes. That isolates the
    paraphrase effect from the item effect.
    """
    rng = random.Random(seed)
    k = len(rows)
    b = len(rows[0])
    row_totals = [sum(rows[j][i] for j in range(k)) for i in range(b)]
    qs, sds, ranges = [], [], []
    positions = list(range(k))
    for _ in range(reps):
        col_totals = [0] * k
        for i in range(b):
            for j in rng.sample(positions, row_totals[i]):
                col_totals[j] += 1
        gbar = sum(col_totals) / k
        den = k * sum(row_totals) - sum(l * l for l in row_totals)
        qs.append(k * (k - 1) * sum((g - gbar) ** 2 for g in col_totals) / den if den else 0.0)
        accs = [c / b for c in col_totals]
        sds.append(stdev(accs))
        ranges.append(max(accs) - min(accs))
    return {"q": qs, "sd": sds, "range": ranges}


def _upper_p(observed, null_values):
    """One-sided p with the observed value included, so p is never reported as exactly 0."""
    ge = sum(1 for v in null_values if v >= observed)
    return (ge + 1) / (len(null_values) + 1)


def spread_test(rows, reps=1000, seed=11):
    q = cochran_q(rows)
    null = permutation_null(rows, reps=reps, seed=seed)
    b = len(rows[0])
    accs = [sum(r) / b for r in rows]
    obs_sd, obs_range = stdev(accs), max(accs) - min(accs)
    return {
        "k_paraphrases": len(rows),
        "b_items": b,
        "cochran_q": q,
        "q_p_value": _upper_p(q, null["q"]) if q is not None else None,
        "observed_sd": obs_sd,
        "null_sd_mean": mean(null["sd"]),
        "null_sd_p95": percentile(null["sd"], 0.95),
        "sd_p_value": _upper_p(obs_sd, null["sd"]),
        "observed_range": obs_range,
        "null_range_mean": mean(null["range"]),
        "null_range_p95": percentile(null["range"], 0.95),
        "range_p_value": _upper_p(obs_range, null["range"]),
        "permutations": reps,
    }


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else float("nan")


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    return pearson(_ranks(xs), _ranks(ys))


def split_half_reliability(rows, reps=200, seed=5):
    """Mean Spearman-Brown corrected split-half correlation of the per-paraphrase accuracy.

    Returns the raw half correlation too, because the correction assumes the halves are parallel
    tests and that assumption is worth being able to see past.
    """
    rng = random.Random(seed)
    b = len(rows[0])
    idx = list(range(b))
    half = b // 2
    raws, corrected = [], []
    for _ in range(reps):
        rng.shuffle(idx)
        a, c = idx[:half], idx[half:half * 2]
        xa = [mean(r[i] for i in a) for r in rows]
        xc = [mean(r[i] for i in c) for r in rows]
        r = pearson(xa, xc)
        if r != r:      # NaN when one half has zero variance across paraphrases
            continue
        raws.append(r)
        corrected.append(2 * r / (1 + r) if r > -1 else float("nan"))
    return {
        "splits": len(raws),
        "half_correlation": mean(raws),
        "spearman_brown": mean(c for c in corrected if c == c),
    }


def holm(pvalues):
    """Holm-Bonferroni adjusted p-values, in the input order."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m = len(pvalues)
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        val = min(1.0, (m - rank) * pvalues[i])
        running = max(running, val)
        adj[i] = running
    return adj


def spearman_permutation_p(xs, ys, reps=2000, seed=3):
    """Two-sided p for a Spearman correlation, by shuffling one side."""
    obs = abs(spearman(xs, ys))
    rng = random.Random(seed)
    ys2 = list(ys)
    hits = 0
    for _ in range(reps):
        rng.shuffle(ys2)
        if abs(spearman(xs, ys2)) >= obs:
            hits += 1
    return (hits + 1) / (reps + 1)
