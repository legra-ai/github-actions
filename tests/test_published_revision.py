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
                patch.object(publish, 'await_publication') as verify:
            verifier.return_value.check.side_effect = [NotPublished('missing'), None]
            publish.main()
        cargo.assert_called_once()
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
