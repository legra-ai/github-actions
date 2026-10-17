"""An already published version is not sufficient evidence for a successful retry."""
import importlib.util
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / '.github/actions/monitor-release'))
from release_sources import NotPublished

source = pathlib.Path(__file__).parents[1] / '.github/actions/publish-tested-crate/publish.py'
spec = importlib.util.spec_from_file_location('publish', source)
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class PublishedRevisionTests(unittest.TestCase):
    def test_successful_cargo_upload_still_requires_public_archive_verification(self):
        with patch.dict(os.environ, RELEASE_CRATE='example', RELEASE_VERSION='1.2.3',
                        RELEASE_REVISION='a' * 40), \
                patch.object(publish.subprocess, 'check_output', return_value='a' * 40), \
                patch.object(publish.subprocess, 'run') as cargo, \
                patch.object(publish, 'Verifier') as verifier, \
                patch.object(publish, 'assert_clean_package') as clean, \
                patch.object(publish, 'await_publication') as verify:
            verifier.return_value.check.side_effect = [NotPublished('missing'), None]
            publish.main()
        cargo.assert_called_once()
        clean.assert_called_once_with('example')
        verify.assert_called_once_with(verifier.return_value.check, 300)

    def test_existing_mismatched_archive_is_never_republished(self):
        with patch.dict(os.environ, RELEASE_CRATE='example', RELEASE_VERSION='1.2.3',
                        RELEASE_REVISION='a' * 40), \
                patch.object(publish.subprocess, 'check_output', return_value='a' * 40), \
                patch.object(publish.subprocess, 'run') as cargo, \
                patch.object(publish, 'Verifier') as verifier:
            verifier.return_value.check.side_effect = ValueError('source differs')
            with self.assertRaisesRegex(ValueError, 'source differs'):
                publish.main()
        cargo.assert_not_called()

    def test_existing_verified_archive_requires_no_upload(self):
        with patch.dict(os.environ, RELEASE_CRATE='example', RELEASE_VERSION='1.2.3',
                        RELEASE_REVISION='a' * 40), \
                patch.object(publish.subprocess, 'check_output', return_value='a' * 40), \
                patch.object(publish.subprocess, 'run') as cargo, \
                patch.object(publish, 'Verifier') as verifier:
            publish.main()
        verifier.return_value.check.assert_called_once()
        cargo.assert_not_called()

class PackageInputTests(unittest.TestCase):
    def test_same_head_with_modified_tracked_source_cannot_publish(self):
        import contextlib
        import subprocess
        import tempfile
        root = source.parents[3]
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['git', 'clone', '--quiet', '--local', str(root), directory], check=True)
            (pathlib.Path(directory) / 'README.md').write_text('modified after validation\n')
            with contextlib.chdir(directory), self.assertRaises(subprocess.CalledProcessError):
                publish.assert_clean_package('example')

    def test_untracked_packaged_source_cannot_hide_behind_allow_dirty(self):
        import contextlib
        import subprocess
        import tempfile
        root = source.parents[3]
        import io
        from unittest.mock import MagicMock
        real_popen = subprocess.Popen
        listing = MagicMock()
        listing.__enter__.return_value = listing
        listing.stdout = io.StringIO('Cargo.toml.orig\n.cargo_vcs_info.json\nREADME.md\nuntracked.rs\n')
        listing.poll.return_value = None
        listing.wait.return_value = 0
        def spawn(args, **kwargs):
            return listing if args[0] == 'cargo' else real_popen(args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['git', 'clone', '--quiet', '--local', str(root), directory], check=True)
            (pathlib.Path(directory) / 'untracked.rs').write_text('fn main() {}\n')
            with contextlib.chdir(directory), patch.object(publish.subprocess, 'Popen', side_effect=spawn):
                with self.assertRaisesRegex(ValueError, 'untracked.rs'):
                    publish.assert_clean_package('example')

    def test_package_file_limit_stops_the_producer(self):
        from unittest.mock import MagicMock
        listing = MagicMock()
        listing.__enter__.return_value = listing
        listing.stdout = ('.cargo_vcs_info.json\n' for _ in range(10000))
        listing.poll.return_value = None
        listing.wait.return_value = 0
        with patch.object(publish.subprocess, 'run'), patch.object(publish.subprocess, 'Popen', return_value=listing):
            with self.assertRaisesRegex(ValueError, '5,000-file'):
                publish.assert_clean_package('example')
        listing.kill.assert_called_once()
