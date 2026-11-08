"""Alpha source identity must remain verifiable across all registries."""
import contextlib
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / '.github/actions/verify-registry-publication'))
SPEC = importlib.util.spec_from_file_location('alpha_verification', ROOT / '.github/actions/verify-registry-publication/verification.py')
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class AlphaPublicationTests(unittest.TestCase):
    def test_semver_candidates_are_valid_for_cargo_and_npm(self):
        for version in ['0.1.0-alpha.1', '0.1.0-beta.2', '0.1.0-rc.3']:
            for registry in ['crates', 'npm']:
                with self.subTest(version=version, registry=registry):
                    verifier = verification.Verifier(Mock(), registry, 'example', version,
                                                     'a' * 40, {'files': {'example.tgz': 'b' * 64}})
                    self.assertEqual(verifier.version, version)

    def test_pypi_normalizes_semver_alpha_without_changing_source_identity(self):
        payload = b'wheel'
        digest = hashlib.sha256(payload).hexdigest()
        api = Mock()
        api.json.return_value = {'info': {'version': '0.1.0a1'}, 'urls': [
            {'filename': 'example.whl', 'digests': {'sha256': digest}, 'url': 'https://example/wheel'}]}
        api.download.return_value = contextlib.nullcontext((None, digest))
        verifier = verification.Verifier(api, 'pypi', 'example', '0.1.0-alpha.1', 'a' * 40,
                                        {'files': {'example.whl': digest}})
        verifier.check()
        self.assertEqual(verifier.tag_revision('0.1.0-alpha.1'), 'a' * 40)
        self.assertTrue(api.json.call_args.args[0].endswith('/0.1.0a1/json'))

    def test_pypi_wrong_candidate_is_not_accepted(self):
        api = Mock()
        api.json.return_value = {'info': {'version': '0.1.0a2'}, 'urls': []}
        verifier = verification.Verifier(api, 'pypi', 'example', '0.1.0-alpha.1', 'a' * 40,
                                        {'files': {'example.whl': 'b' * 64}})
        with self.assertRaises(verification.NotPublished):
            verifier.check()

    def test_unknown_channels_and_malformed_candidates_fail(self):
        for version in ['0.1.0-preview.1', '0.1.0-alpha', '0.1.0-alpha.01', '0.1.0a1', '01.1.0']:
            with self.subTest(version=version), self.assertRaises(ValueError):
                verification.Verifier(Mock(), 'crates', 'example', version, 'a' * 40, None)


if __name__ == '__main__':
    unittest.main()
