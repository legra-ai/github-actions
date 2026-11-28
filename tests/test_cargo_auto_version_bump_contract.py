"""Regression tests for the automatic Cargo release workflow contract."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
WORKFLOW = (ROOT / ".github/workflows/cargo-auto-version-bump.yml").read_text(
    encoding="utf-8"
)
ACTION = (ROOT / ".github/actions/generate-changelog/action.yml").read_text(
    encoding="utf-8"
)


class CargoAutoVersionBumpContractTests(unittest.TestCase):
    """Protect release ordering around changelog generation."""

    def test_changelog_uses_existing_bumped_commit_before_tag_creation(self) -> None:
        """Changelog generation must not resolve a tag that is not created yet."""
        self.assertIn("  revision:\n", ACTION)
        self.assertIn('--at "${{ inputs.revision }}"', ACTION)
        self.assertIn("          revision: HEAD\n", WORKFLOW)
        self.assertNotIn("          release-tag: v${{ env.NEW_VERSION }}\n", WORKFLOW)

    def test_manifest_version_is_the_bump_authority(self) -> None:
        """Automatic bumps must not derive a downgrade from stale Git tags."""
        self.assertIn("cargo version-info bump --patch", WORKFLOW)
        self.assertNotIn("cog bump --patch", WORKFLOW)


    def test_version_commit_is_made_by_the_release_writer_app(self) -> None:
        """The bump commit lands on main, past the required checks, only as the writer App."""
        step = WORKFLOW.split("      - name: Push verified commit via GraphQL\n", 1)[1].split("        run: |", 1)[0]
        self.assertIn("GH_TOKEN: ${{ steps.writer.outputs.token }}", step)
        self.assertIn("app-id: ${{ secrets.RELEASE_WRITER_APP_ID }}", WORKFLOW)
        self.assertNotIn("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n          REPO:", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
