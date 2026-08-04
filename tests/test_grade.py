"""Grading, and the negative controls that show each check can fail.

Every test here has a partner whose name ends in `_negative_control`. The partner deliberately
breaks something and asserts the check notices. A test suite where every assertion is satisfied
by construction proves nothing about the code, and the way to find that out is to break the code
on purpose and watch the assertion move.
"""

import unittest

from pspread import grade


class IntegerExtraction(unittest.TestCase):
    CASES = [
        ("3901", "3901", grade.CORRECT),
        ("The answer is 3901.", "3901", grade.CORRECT),
        ("47 x 83 = 3901", "3901", grade.CORRECT),
        ("3,901", "3901", grade.CORRECT),
        ("47 times 83 equals 3902", "3901", grade.WRONG),
        ("**3901**", "3901", grade.CORRECT),
        ("I cannot compute that.", "3901", grade.UNPARSEABLE),
        ("", "3901", grade.UNPARSEABLE),
    ]

    def test_last_number_is_the_prediction(self):
        for text, answer, expected in self.CASES:
            with self.subTest(text=text):
                strict, _, _ = grade.grade_one(text, answer, "integer")
                self.assertEqual(strict, expected)

    def test_last_number_is_the_prediction_negative_control(self):
        """A first-number rule disagrees with a last-number rule on real model output.

        If it did not, this suite would pass equally on a grader that read the wrong end of the
        response, and the specification the independent checker follows would not be pinned down
        by anything.
        """
        text = "47 x 83 = 3901"
        first = grade.candidates(text, "integer")[0]
        last = grade.candidates(text, "integer")[-1]
        self.assertNotEqual(first, last)
        self.assertEqual(last, "3901")

    def test_commas_inside_numbers_are_removed_but_others_are_not(self):
        self.assertEqual(grade.candidates("3,901", "integer"), ["3901"])
        self.assertEqual(grade.candidates("12, 34", "integer"), ["12", "34"])

    def test_commas_inside_numbers_are_removed_but_others_are_not_negative_control(self):
        """Without the rule, a thousands separator splits one number into two, and the last of
        those two is 901. That is the failure the rule exists to prevent, and it is the reason
        the check above is not vacuous."""
        no_rule = [c for c in "3,901".split(",")]
        self.assertEqual(no_rule[-1], "901")
        self.assertNotEqual(no_rule, grade.candidates("3,901", "integer"))
        # and the rule must not go the other way and glue a comma-separated list together
        self.assertEqual(grade.candidates("12, 34", "integer"), ["12", "34"])


class LabelExtraction(unittest.TestCase):
    def test_whole_words_only(self):
        self.assertEqual(grade.candidates("It is not the case.", "label"), [])
        self.assertEqual(grade.candidates("unknowable", "label"), [])
        self.assertEqual(grade.candidates("Answer: UNKNOWN", "label"), ["unknown"])
        self.assertEqual(grade.candidates("no, wait, yes", "label"), ["no", "yes"])

    def test_whole_words_only_negative_control(self):
        """A substring rule fires on `not` and `unknowable`, which would silently score
        refusals as answers."""
        text = "It is not the case, and the outcome is unknowable."
        substring_hits = [w for w in ("yes", "no", "unknown") if w in text.lower()]
        self.assertTrue(substring_hits, "the control needs the substring rule to fire")
        self.assertEqual(grade.candidates(text, "label"), [])


class Accounting(unittest.TestCase):
    ANSWERS = {"a": "10", "b": "20", "c": "30", "d": "40"}
    RECORDS = [("a", "10"), ("b", "99"), ("c", "no digits here"), ("d", None)]

    def test_counts_sum_to_attempts_and_keep_the_four_outcomes_apart(self):
        g = grade.grade_group(self.RECORDS, self.ANSWERS, "integer")
        self.assertEqual(g["attempts"], 4)
        self.assertEqual((g["correct"], g["wrong"], g["unparseable"], g["error"]), (1, 1, 1, 1))
        self.assertEqual(g["correct"] + g["wrong"] + g["unparseable"] + g["error"],
                         g["attempts"])

    def test_counts_sum_to_attempts_and_keep_the_four_outcomes_apart_negative_control(self):
        """Folding unparseable into wrong changes the reported numbers, so the distinction is
        load bearing rather than cosmetic."""
        g = grade.grade_group(self.RECORDS, self.ANSWERS, "integer")
        folded_wrong = g["wrong"] + g["unparseable"]
        self.assertNotEqual(folded_wrong, g["wrong"])
        self.assertGreater(g["unparseable"], 0)

    def test_a_failed_call_is_not_a_wrong_answer(self):
        """Errored calls leave the denominator, so an unreachable server cannot look like a
        model that got everything wrong."""
        g = grade.grade_group(self.RECORDS, self.ANSWERS, "integer")
        self.assertEqual(g["error"], 1)
        self.assertAlmostEqual(g["strict_accuracy"], 1 / 3)

    def test_a_failed_call_is_not_a_wrong_answer_negative_control(self):
        """With the error counted as an attempt the accuracy would be 1/4, so the exclusion
        really does move the number."""
        g = grade.grade_group(self.RECORDS, self.ANSWERS, "integer")
        naive = g["correct"] / g["attempts"]
        self.assertAlmostEqual(naive, 0.25)
        self.assertNotAlmostEqual(naive, g["strict_accuracy"])

    def test_strict_and_parsed_and_lenient_are_three_different_numbers(self):
        records = [("a", "10"), ("b", "the answer is 20 or maybe 21"), ("c", "sorry"),
                   ("d", "40")]
        g = grade.grade_group(records, self.ANSWERS, "integer")
        self.assertAlmostEqual(g["strict_accuracy"], 2 / 4)
        self.assertAlmostEqual(g["parsed_accuracy"], 2 / 3)
        self.assertAlmostEqual(g["lenient_accuracy"], 3 / 4)

    def test_strict_and_parsed_and_lenient_are_three_different_numbers_negative_control(self):
        """On responses with a single clean number all three collapse to the same value, which
        is why the test above uses a response the three definitions disagree about."""
        records = [("a", "10"), ("b", "99"), ("c", "99"), ("d", "40")]
        g = grade.grade_group(records, self.ANSWERS, "integer")
        self.assertEqual(g["strict_accuracy"], g["parsed_accuracy"])
        self.assertEqual(g["strict_accuracy"], g["lenient_accuracy"])


if __name__ == "__main__":
    unittest.main()
