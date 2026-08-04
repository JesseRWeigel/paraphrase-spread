"""The task definitions, the paraphrase filter, and the feature extractors.

Same rule as the other test files: every check is paired with a negative control that shows the
check discriminates rather than accepting everything put in front of it.
"""

import unittest

from pspread import features, paraphrase, tasks


class TaskGroundTruth(unittest.TestCase):
    def test_every_multiplication_answer_is_the_product_of_its_own_factors(self):
        """The answer key is recomputed here from the item's identifier, which is the same
        route `scripts/check_independent.py` takes, so a typo in the key cannot survive."""
        for item in tasks.MULT.items:
            left, right = item.key[len("mult-"):].split("x")
            self.assertEqual(item.answer, str(int(left) * int(right)))
            self.assertEqual(item.slots["a"], left)
            self.assertEqual(item.slots["b"], right)

    def test_every_multiplication_answer_is_the_product_of_its_own_factors_negative_control(self):
        """A key built from the wrong operation fails the same assertion, so the check above is
        looking at something."""
        item = tasks.MULT.items[0]
        left, right = item.key[len("mult-"):].split("x")
        self.assertNotEqual(item.answer, str(int(left) + int(right)))

    def test_the_item_set_is_not_trivially_easy(self):
        """Factors ending in 0 or 1, and squares, are excluded because they are much easier and
        would compress the accuracy range for reasons unrelated to wording."""
        for item in tasks.MULT.items:
            a, b = int(item.slots["a"]), int(item.slots["b"])
            self.assertNotIn(a % 10, (0, 1))
            self.assertNotIn(b % 10, (0, 1))
            self.assertNotEqual(a, b)

    def test_the_item_set_is_not_trivially_easy_negative_control(self):
        self.assertIn(20 % 10, (0, 1))
        self.assertIn(41 % 10, (0, 1))

    def test_items_are_unique_and_the_set_is_reproducible(self):
        keys = [i.key for i in tasks.MULT.items]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, [i.key for i in tasks._mult_items()])

    def test_items_are_unique_and_the_set_is_reproducible_negative_control(self):
        self.assertNotEqual([i.key for i in tasks._mult_items(seed=1)],
                            [i.key for i in tasks._mult_items(seed=2)])

    def test_the_four_conditional_forms_carry_their_classical_answers(self):
        expect = {"mp": "yes", "mt": "no", "ac": "unknown", "da": "unknown"}
        seen = set()
        for item in tasks.ENTAIL.items:
            prefix = item.key.split("-")[0]
            seen.add(prefix)
            self.assertEqual(item.answer, expect[prefix], item.key)
        self.assertEqual(seen, set(expect))

    def test_the_four_conditional_forms_carry_their_classical_answers_negative_control(self):
        """Affirming the consequent is the item type that separates a model tracking direction
        from one pattern-matching on if/then, so it must not share an answer with modus ponens."""
        mp = next(i for i in tasks.ENTAIL.items if i.key.startswith("mp"))
        ac = next(i for i in tasks.ENTAIL.items if i.key.startswith("ac"))
        self.assertNotEqual(mp.answer, ac.answer)
        self.assertEqual(mp.slots["rule"], ac.slots["rule"])

    def test_the_answer_is_never_derivable_from_the_wording_alone(self):
        """Each of the three answers appears on more than one item, so a model that always says
        the same word cannot score well."""
        counts = {}
        for item in tasks.ENTAIL.items:
            counts[item.answer] = counts.get(item.answer, 0) + 1
        self.assertEqual(set(counts), {"yes", "no", "unknown"})
        best_constant = max(counts.values()) / len(tasks.ENTAIL.items)
        self.assertLessEqual(best_constant, 0.55)

    def test_the_answer_is_never_derivable_from_the_wording_alone_negative_control(self):
        skewed = ["yes"] * 20 + ["no"] * 4
        best_constant = max(skewed.count(v) for v in set(skewed)) / len(skewed)
        self.assertGreater(best_constant, 0.55)


class Validation(unittest.TestCase):
    GOOD = "Multiply {a} by {b} and reply with the plain integer only."

    def test_a_well_formed_template_is_accepted(self):
        self.assertIsNone(paraphrase.validate(self.GOOD, tasks.MULT))

    def test_a_well_formed_template_is_accepted_negative_control(self):
        broken = [
            ("Multiply {a} by 12 and give the plain integer.", "placeholder"),
            ("Multiply {a} by {b} by {b}, plain integer only.", "placeholder"),
            ("Multiply {a} by {b} and {c}, plain integer only.", "unexpected"),
            ("{a}{b}", "length"),
            ("Multiply {a} by {b}; for example the answer might be 1234.", "digit"),
            ("Multiply {a}\nby {b}.", "multiline"),
        ]
        for text, expect in broken:
            with self.subTest(text=text):
                reason = paraphrase.validate(text, tasks.MULT)
                self.assertIsNotNone(reason, f"{text!r} was accepted")
                self.assertIn(expect, reason)

    def test_the_entail_filter_requires_all_three_option_words(self):
        good = ("{rule} {fact} Does {target} follow? Say YES, NO, or UNKNOWN.")
        self.assertIsNone(paraphrase.validate(good, tasks.ENTAIL))

    def test_the_entail_filter_requires_all_three_option_words_negative_control(self):
        """A wording that offers 'indeterminate' instead of UNKNOWN is a fine paraphrase for a
        human and unreadable to the grader, so it has to be rejected at generation time rather
        than scored as a failure later."""
        bad = "{rule} {fact} Does {target} follow? Say YES, NO, or INDETERMINATE."
        self.assertIsNotNone(paraphrase.validate(bad, tasks.ENTAIL))

    def test_duplicates_are_dropped_after_normalisation(self):
        pool = ["Multiply {a} by {b}.", "multiply  {a}   by {b}!", "Times {a} and {b}."]
        kept, dropped = paraphrase.dedupe(pool)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 1)

    def test_duplicates_are_dropped_after_normalisation_negative_control(self):
        """Case-sensitive exact matching would keep both spellings, so normalisation is doing
        work rather than decorating the comparison."""
        pool = ["Multiply {a} by {b}.", "multiply  {a}   by {b}!"]
        self.assertEqual(len(set(pool)), 2)
        self.assertEqual(len(paraphrase.dedupe(pool)[0]), 1)


class Features(unittest.TestCase):
    def test_each_binary_feature_fires_on_a_template_that_has_it(self):
        cases = {
            "is_question": "What is {a} times {b}?",
            "role_frame": "You are a calculator. Multiply {a} by {b}.",
            "think_cue": "Think carefully, then multiply {a} by {b}.",
            "immediate_cue": "Multiply {a} by {b}. Answer immediately.",
            "format_instruction": "Multiply {a} by {b}. Give the number and nothing else.",
            "politeness": "Please multiply {a} by {b}.",
            "markdown": "Multiply {a} by {b}. **Integer only.**",
            "numbered_list": "1. Multiply {a} by {b}. 2. Report it.",
            "shouty_caps": "MULTIPLY {a} by {b} and report ONLY the INTEGER.",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assertEqual(features.extract(text)[name], 1.0)

    def test_each_binary_feature_fires_on_a_template_that_has_it_negative_control(self):
        """The same features must be 0 on a bare template. A detector that always returns 1
        would pass the test above on its own."""
        bare = "Multiply {a} by {b}."
        got = features.extract(bare)
        for name in ("is_question", "role_frame", "think_cue", "immediate_cue",
                     "format_instruction", "politeness", "markdown", "numbered_list",
                     "shouty_caps"):
            with self.subTest(name=name):
                self.assertEqual(got[name], 0.0)

    def test_slot_position_runs_from_zero_to_one(self):
        early = features.extract("{a} times {b}, integer please, thank you very much indeed.")
        late = features.extract("Please give the plain integer product of these two: {a}, {b}.")
        self.assertLess(early["slot_position"], 0.1)
        self.assertGreater(late["slot_position"], 0.5)

    def test_slot_position_runs_from_zero_to_one_negative_control(self):
        same = "Multiply {a} by {b}."
        self.assertEqual(features.extract(same)["slot_position"],
                         features.extract(same)["slot_position"])
        self.assertNotEqual(features.extract("{a} x {b} as an integer, no commas, thank you")[
                                "slot_position"],
                            features.extract("As an integer with no commas: {a} x {b}")[
                                "slot_position"])


if __name__ == "__main__":
    unittest.main()
