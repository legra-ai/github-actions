"""Reusable Cargo maintenance carries one explicit policy through planning and writes."""

from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]


class MaintenanceBumpPolicyTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()

    def test_unspecified_callers_keep_major_policy(self):
        inputs = self.workflow.split('    secrets:', 1)[0]
        self.assertRegex(inputs, r'breaking-change-bump:\n(?:        .*\n)*        default: major\n')

    def test_read_only_plan_and_prepare_receive_the_same_policy(self):
        plan = self.workflow.split('      - id: plan\n', 1)[1].split('      - id: prepare\n', 1)[0]
        prepare = self.workflow.split('      - id: prepare\n', 1)[1].split('      - id: manifest\n', 1)[0]
        for step in (plan, prepare):
            self.assertIn('RELEASE_BREAKING_CHANGE_BUMP: ${{ inputs.breaking-change-bump }}', step)
            self.assertIn('prepare-cargo-release/release.py', step)
        self.assertIn("RELEASE_PLAN_ONLY: 'true'", plan)
        self.assertIn('GH_TOKEN: ${{ github.token }}', plan)
        self.assertNotIn('RELEASE_PLAN_ONLY', prepare)

    def test_invalid_input_fails_before_release_preparation(self):
        validation = self.workflow.split('      - name: Validate maintenance inputs\n', 1)[1].split('      - uses:', 1)[0]
        self.assertIn('RELEASE_BREAKING_CHANGE_BUMP: ${{ inputs.breaking-change-bump }}', validation)
        self.assertIn("os.environ['RELEASE_BREAKING_CHANGE_BUMP'] not in ('major', 'minor')", validation)
        self.assertLess(self.workflow.index('Validate maintenance inputs'), self.workflow.index('      - id: plan\n'))


if __name__ == '__main__':
    unittest.main()
