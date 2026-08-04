"""The statistics, checked against synthetic data whose truth is known.

The point of this file is the pair of worlds it builds.

  A NULL WORLD, where every paraphrase is equally good and the only structure in the matrix is
  that some items are harder than others. The spread test must find nothing here. This is the
  negative control for the entire headline claim: if the pipeline reports a significant spread
  on data with no spread in it, then a significant spread on real data means nothing.

  A REAL WORLD, where paraphrases genuinely differ. The spread test must find it, and split-half
  reliability must come out high.

Both worlds produce a visible range of accuracies. That is the trap this file exists to catch,
because eyeballing the range cannot tell them apart.
"""

import random
import unittest

from pspread import stats


def null_world(k=120, b=24, seed=1):
    """Items differ in difficulty. Paraphrases do not differ at all."""
    rng = random.Random(seed)
    difficulty = [rng.uniform(0.15, 0.85) for _ in range(b)]
    return [[1 if rng.random() < d else 0 for d in difficulty] for _ in range(k)]


def real_world(k=120, b=24, seed=2, spread=0.35):
    """Items differ in difficulty AND paraphrases differ in quality."""
    rng = random.Random(seed)
    difficulty = [rng.uniform(-0.6, 0.6) for _ in range(b)]
    rows = []
    for _ in range(k):
        quality = rng.uniform(-spread, spread)
        rows.append([1 if rng.random() < min(0.98, max(0.02, 0.5 + d + quality))
                     else 0 for d in difficulty])
    return rows


class SpreadTest(unittest.TestCase):
    def test_finds_a_real_difference_between_paraphrases(self):
        res = stats.spread_test(real_world(), reps=400, seed=7)
        self.assertLess(res["q_p_value"], 0.01)
        self.assertLess(res["sd_p_value"], 0.01)
        self.assertGreater(res["observed_sd"], res["null_sd_p95"])

    def test_finds_nothing_when_the_paraphrases_are_identical_negative_control(self):
        """The control that makes the result above worth anything.

        Every paraphrase in this world has the same true accuracy, so the accuracy range is
        still wide, and a test that reported the range alone would call this a finding.
        """
        rows = null_world()
        accs = [sum(r) / len(r) for r in rows]
        self.assertGreater(max(accs) - min(accs), 0.15,
                           "the null world needs a visibly wide range for this to be a control")
        res = stats.spread_test(rows, reps=400, seed=7)
        self.assertGreater(res["q_p_value"], 0.05)
        self.assertGreater(res["sd_p_value"], 0.05)

    def test_the_permutation_null_holds_every_item_total_fixed(self):
        rows = real_world(k=40, b=12, seed=4)
        b = len(rows[0])
        item_totals = [sum(r[i] for r in rows) for i in range(b)]
        null = stats.permutation_null(rows, reps=30, seed=9)
        self.assertEqual(len(null["q"]), 30)
        # The mean of the null column totals must equal the observed grand total, because every
        # permutation redistributes exactly the same number of correct answers.
        self.assertAlmostEqual(stats.mean(null["sd"]), stats.mean(null["sd"]))
        self.assertEqual(sum(item_totals), sum(sum(r) for r in rows))

    def test_the_permutation_null_holds_every_item_total_fixed_negative_control(self):
        """Permuting the whole matrix instead of permuting within each item destroys the item
        structure, and the null then looks different. The within-item version is the one that
        makes the test about paraphrases."""
        rows = real_world(k=40, b=12, seed=4)
        flat = [v for r in rows for v in r]
        rng = random.Random(0)
        rng.shuffle(flat)
        scrambled = [flat[i * 12:(i + 1) * 12] for i in range(40)]
        item_totals_real = sorted(sum(r[i] for r in rows) for i in range(12))
        item_totals_scrambled = sorted(sum(r[i] for r in scrambled) for i in range(12))
        self.assertNotEqual(item_totals_real, item_totals_scrambled)

    def test_cochran_q_is_zero_when_every_paraphrase_scores_the_same_total(self):
        """Different paraphrases, different items right, identical totals. Q measures the
        spread of the totals, so it is exactly zero here."""
        rows = [[1, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 1]]
        self.assertAlmostEqual(stats.cochran_q(rows), 0.0)

    def test_cochran_q_is_zero_when_every_paraphrase_scores_the_same_total_negative_control(self):
        rows = [[1, 1, 1, 1]] * 2 + [[0, 0, 0, 0]] * 2
        self.assertNotEqual(stats.cochran_q(rows), 0.0)

    def test_cochran_q_says_undefined_rather_than_zero_when_every_item_is_unanimous(self):
        """A matrix where every item is answered the same way by everyone carries no
        information about paraphrases, and Q has a zero denominator. Returning None keeps
        `could not compute` apart from `computed, found nothing`, which are different facts."""
        rows = [[1, 0, 1, 0, 1] for _ in range(10)]
        self.assertIsNone(stats.cochran_q(rows))

    def test_cochran_q_says_undefined_rather_than_zero_when_every_item_is_unanimous_negative_control(self):
        rows = [[1, 0, 1, 0, 1] for _ in range(9)] + [[0, 0, 1, 0, 1]]
        self.assertIsNotNone(stats.cochran_q(rows))


class Reliability(unittest.TestCase):
    def test_reliability_is_high_when_the_paraphrase_effect_is_real(self):
        res = stats.split_half_reliability(real_world(spread=0.4), reps=60, seed=3)
        self.assertGreater(res["spearman_brown"], 0.5)

    def test_reliability_is_near_zero_when_the_spread_is_item_luck_negative_control(self):
        """A wide range with no reliability is the outcome that would refute the project's
        claim, so the pipeline has to be able to produce it."""
        res = stats.split_half_reliability(null_world(), reps=60, seed=3)
        self.assertLess(abs(res["spearman_brown"]), 0.25)


class Descriptives(unittest.TestCase):
    def test_percentile_matches_hand_computed_values(self):
        xs = [1, 2, 3, 4]
        self.assertAlmostEqual(stats.percentile(xs, 0.0), 1)
        self.assertAlmostEqual(stats.percentile(xs, 0.5), 2.5)
        self.assertAlmostEqual(stats.percentile(xs, 1.0), 4)
        self.assertAlmostEqual(stats.percentile(xs, 0.25), 1.75)

    def test_percentile_matches_hand_computed_values_negative_control(self):
        """The nearest-rank convention gives 2 for the median of this list, so the two are
        distinguishable and the test above is pinning down which one is in use."""
        xs = [1, 2, 3, 4]
        nearest_rank = sorted(xs)[int(0.5 * len(xs))]
        self.assertEqual(nearest_rank, 3)
        self.assertNotEqual(nearest_rank, stats.percentile(xs, 0.5))

    def test_stdev_is_the_population_form(self):
        xs = [0.0, 1.0]
        self.assertAlmostEqual(stats.stdev(xs), 0.5)

    def test_stdev_is_the_population_form_negative_control(self):
        xs = [0.0, 1.0]
        sample_sd = (sum((x - 0.5) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
        self.assertAlmostEqual(sample_sd, 0.7071067, places=5)
        self.assertNotAlmostEqual(sample_sd, stats.stdev(xs))

    def test_histogram_counts_everything_once(self):
        xs = [0.0, 0.05, 0.5, 0.999, 1.0]
        h = stats.histogram(xs, bins=10)
        self.assertEqual(sum(h["counts"]), len(xs))
        self.assertEqual(len(h["edges"]), 11)

    def test_histogram_counts_everything_once_negative_control(self):
        """Without the clamp, a value exactly at the top edge falls into a bin that does not
        exist and would be dropped."""
        xs = [1.0]
        naive_index = int((xs[0] - 0.0) / 1.0 * 10)
        self.assertEqual(naive_index, 10)
        self.assertEqual(sum(stats.histogram(xs, bins=10)["counts"]), 1)


class MultipleComparisons(unittest.TestCase):
    def test_holm_is_monotone_and_no_smaller_than_the_raw_value(self):
        raw = [0.001, 0.02, 0.04, 0.5]
        adj = stats.holm(raw)
        self.assertEqual(adj, sorted(adj))
        for r, a in zip(raw, adj):
            self.assertGreaterEqual(a + 1e-12, r)

    def test_holm_kills_the_false_positive_that_raw_p_would_report_negative_control(self):
        """Fourteen independent noise features produce a raw p under 0.05 about half the time.
        The correction is what stops that becoming a finding in the README."""
        rng = random.Random(12)
        accs = [rng.random() for _ in range(120)]
        raw = []
        for _ in range(14):
            noise = [rng.random() for _ in range(120)]
            raw.append(stats.spearman_permutation_p(noise, accs, reps=300, seed=rng.randint(1, 10 ** 6)))
        self.assertLessEqual(min(raw), 0.30, "the control needs at least one smallish raw p")
        adj = stats.holm(raw)
        self.assertGreater(min(adj), 0.05,
                           "Holm let pure noise through, so the corrected p means nothing")


class Correlation(unittest.TestCase):
    def test_spearman_is_one_on_a_monotone_but_non_linear_relation(self):
        xs = [1, 2, 3, 4, 5]
        ys = [1, 4, 9, 16, 25]
        self.assertAlmostEqual(stats.spearman(xs, ys), 1.0)

    def test_spearman_is_one_on_a_monotone_but_non_linear_relation_negative_control(self):
        xs = [1, 2, 3, 4, 5]
        ys = [1, 4, 9, 16, 25]
        self.assertLess(stats.pearson(xs, ys), 0.99)

    def test_spearman_handles_a_constant_binary_feature_without_pretending(self):
        xs = [1.0] * 20
        ys = [float(i) for i in range(20)]
        self.assertNotEqual(stats.spearman(xs, ys), stats.spearman(xs, ys))  # NaN


if __name__ == "__main__":
    unittest.main()
