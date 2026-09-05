import copy
import json
from pathlib import Path
import unittest
from onboarding import assess

ROOT = Path(__file__).resolve().parents[1]


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.answers = json.loads((ROOT / 'examples/answers.json').read_text())
        self.options = json.loads((ROOT / 'examples/options.json').read_text())

    def test_low_effort_matches_without_granting_authority(self):
        result = assess(self.answers, self.options)
        self.assertEqual(result['recommendation']['id'], 'small-supported-example')
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(result['status'], 'example_fit')

    def test_no_money_or_time_does_not_invent_an_autonomous_solution(self):
        for key in ('setup_eur', 'monthly_eur', 'learning_hours', 'minutes_per_week'):
            self.answers[key] = 0
        result = assess(self.answers, self.options)
        self.assertIsNone(result['recommendation'])
        self.assertEqual(result['status'], 'no_supported_fit')

    def test_local_only_is_not_silently_relaxed(self):
        self.answers['data_preference'] = 'local_only'
        result = assess(self.answers, self.options)
        self.assertIsNone(result['recommendation'])
        self.assertIn('local-only', ' '.join(result['alternatives'][0]['reasons']))

    def test_learning_preference_with_resources_selects_local_path(self):
        self.answers.update(setup_eur=600, learning_hours=20, minutes_per_week=90,
                            preference='learn', data_preference='local_only')
        result = assess(self.answers, self.options)
        self.assertEqual(result['recommendation']['id'], 'local-learning-example')

    def test_serious_impact_cannot_be_offset_by_budget_or_risk_tolerance(self):
        self.answers.update(impact='serious', setup_eur=100000, acceptable_loss_eur=100000)
        result = assess(self.answers, self.options)
        self.assertEqual(result['status'], 'specialist_review')
        self.assertFalse(result['execution_authorized'])

    def test_unverified_recovery_never_recommended(self):
        self.options[0]['recovery_verified'] = False
        result = assess(self.answers, self.options)
        self.assertIsNone(result['recommendation'])
        self.assertEqual(result['alternatives'][0]['status'], 'needs_assessment')

    def test_unknown_resource_cost_does_not_mean_free(self):
        self.options[0]['monthly_eur'] = None
        result = assess(self.answers, self.options)
        self.assertIsNone(result['recommendation'])
        self.assertIn('not assessed', ' '.join(result['alternatives'][0]['reasons']))

    def test_invalid_numbers_and_boolean_capabilities_refused(self):
        for value in (-1, True, float('nan'), float('inf'), '10'):
            answers = dict(self.answers, monthly_eur=value)
            with self.assertRaises(ValueError):
                assess(answers, self.options)
        options = copy.deepcopy(self.options)
        options[0]['recovery_verified'] = 'true'
        with self.assertRaises(ValueError):
            assess(self.answers, options)

    def test_loss_tolerance_does_not_change_authority(self):
        low = assess(self.answers, self.options)
        self.answers['acceptable_loss_eur'] = 100
        high = assess(self.answers, self.options)
        self.assertEqual(low['recommendation'], high['recommendation'])
        self.assertFalse(high['execution_authorized'])

    def test_no_automation_evidence_leaves_changes_approval_first(self):
        self.options[0]['routine_automation_verified'] = False
        result = assess(self.answers, self.options)
        self.assertIn('changes still need approval', result['recommendation']['automation'])

    def test_options_are_not_mutated_and_duplicate_ids_refused(self):
        before = copy.deepcopy(self.options)
        assess(self.answers, self.options)
        self.assertEqual(before, self.options)
        with self.assertRaises(ValueError):
            assess(self.answers, self.options + [self.options[0]])

    def test_details_preserve_reasons_for_alternatives(self):
        result = assess(self.answers, self.options)
        self.assertTrue(result['alternatives'][0]['reasons'])
        self.assertIn('FICTIONAL', result['recommendation']['evidence'])


if __name__ == '__main__':
    unittest.main()
