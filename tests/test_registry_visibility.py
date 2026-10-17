"""Publication cannot complete before public archives have verified identity."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import zipfile

ROOT = Path(__file__).parents[1]
ACTION = ROOT / '.github/actions/verify-registry-publication'
sys.path.insert(0, str(ACTION))
SPEC = importlib.util.spec_from_file_location('verification', ACTION / 'verification.py')
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


class VisibilityTests(unittest.TestCase):
    def test_only_absence_is_polled_until_public_identity_is_verified(self):
        check = Mock(side_effect=[verification.NotPublished('not indexed'), None])
        clock = Mock(side_effect=[0, 0, 5])
        sleep = Mock()
        verification.await_publication(check, 10, clock=clock, sleep=sleep)
        self.assertEqual(check.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_missing_package_exhausts_a_finite_deadline(self):
        check = Mock(side_effect=verification.NotPublished('wheel missing'))
        with self.assertRaisesRegex(TimeoutError, 'wheel missing'):
            verification.await_publication(check, 10, clock=Mock(side_effect=[0, 10]), sleep=Mock())
        self.assertEqual(check.call_count, 1)

    def test_identity_and_service_errors_fail_without_sleeping(self):
        for error in [ValueError('digest mismatch'), RuntimeError('HTTP 403'), RuntimeError('HTTP 503')]:
            sleep = Mock()
            with self.subTest(error=error), self.assertRaises(type(error)):
                verification.await_publication(Mock(side_effect=error), 10, sleep=sleep)
            sleep.assert_not_called()

    def test_missing_wheel_is_pending_but_wrong_digest_fails_immediately(self):
        api = Mock()
        verifier = verification.Verifier(api, 'pypi', 'example', '1.2.3', 'a' * 40,
                                         {'files': {'example.whl': 'b' * 64}})
        api.json.return_value = {'info': {'version': '1.2.3'}, 'urls': []}
        with self.assertRaises(verification.NotPublished):
            verifier.check()
        api.json.return_value['urls'] = [{'filename': 'example.whl', 'digests': {'sha256': 'c' * 64}}]
        with self.assertRaisesRegex(ValueError, 'mismatched'):
            verifier.check()

    def test_indexed_npm_package_waits_for_the_actual_archive(self):
        api = verification.API('')
        payload = b'preserved npm tarball'
        url = 'https://registry.npmjs.org/example/-/example-1.2.3.tgz'
        manifest = {'files': {'example.tgz': hashlib.sha256(payload).hexdigest()}}
        verifier = verification.Verifier(api, 'npm', 'example', '1.2.3', 'a' * 40, manifest)
        sleep = Mock()
        with patch.object(api, 'json', return_value={'version': '1.2.3', 'dist': {'tarball': url}}), \
                patch('release_http.urlopen', side_effect=[
                    HTTPError(url, 404, 'not visible yet', {}, io.BytesIO()), io.BytesIO(payload)]) as download:
            verification.await_publication(verifier.check, 10, clock=Mock(return_value=0), sleep=sleep)
        self.assertEqual(download.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_archive_absence_exhausts_the_same_visibility_deadline(self):
        api = verification.API('')
        url = 'https://registry.npmjs.org/example/-/example-1.2.3.tgz'
        verifier = verification.Verifier(api, 'npm', 'example', '1.2.3', 'a' * 40,
                                         {'files': {'example.tgz': 'b' * 64}})
        with patch.object(api, 'json', return_value={'version': '1.2.3', 'dist': {'tarball': url}}), \
                patch('release_http.urlopen', side_effect=HTTPError(url, 404, 'absent', {}, io.BytesIO())), \
                self.assertRaisesRegex(TimeoutError, '404'):
            verification.await_publication(verifier.check, 10, clock=Mock(side_effect=[0, 10]), sleep=Mock())

    def test_archive_authentication_and_service_failures_are_not_retried(self):
        for code in [401, 403, 429, 500]:
            api = verification.API('')
            url = 'https://registry.npmjs.org/example/-/example-1.2.3.tgz'
            verifier = verification.Verifier(api, 'npm', 'example', '1.2.3', 'a' * 40,
                                             {'files': {'example.tgz': 'b' * 64}})
            sleep = Mock()
            with self.subTest(code=code), \
                    patch.object(api, 'json', return_value={'version': '1.2.3', 'dist': {'tarball': url}}), \
                    patch('release_http.urlopen', side_effect=HTTPError(url, code, 'failed', {}, io.BytesIO())), \
                    self.assertRaisesRegex(RuntimeError, str(code)):
                verification.await_publication(verifier.check, 10, sleep=sleep)
            sleep.assert_not_called()

    def test_bundle_is_bound_to_validated_source_before_network_access(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'packages.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('manifest.json', json.dumps({
                    'version': '1.2.3', 'revision': 'b' * 40, 'files': {'example.whl': 'c' * 64}}))
            with self.assertRaisesRegex(ValueError, 'revision'):
                verification.load_manifest(path, '1.2.3', 'a' * 40)

    def test_bindings_cannot_be_verified_without_preserved_archive_identity(self):
        for registry in ['npm', 'pypi']:
            with self.subTest(registry=registry), self.assertRaisesRegex(ValueError, 'archive'):
                verification.Verifier(Mock(), registry, 'example', '1.2.3', 'a' * 40, None)

    def test_waiting_budget_is_explicitly_capped(self):
        for timeout in [-1, 0, 601]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                verification.await_publication(Mock(), timeout)


if __name__ == '__main__':
    unittest.main()
