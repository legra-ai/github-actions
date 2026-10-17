"""Draft lookup must preserve identity and distinguish absence from API failure."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('binary_release_lookup', ROOT / '.github/actions/build-tested-binary/binary.py')
binary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binary)


class BinaryReleaseLookupTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, GITHUB_REPOSITORY='owner/example')
        env.start()
        self.addCleanup(env.stop)
        self.info = {'version': '1.2.3'}

    def lookup(self, value):
        return subprocess.CompletedProcess([], 0, json.dumps({'data': {'repository': {'release': value}}}), '')

    def test_existing_draft_is_retrieved_by_id_with_asset_digests(self):
        draft = {'id': 123, 'tag_name': 'v1.2.3', 'draft': True,
                 'assets': [{'name': 'binary.zip', 'digest': 'sha256:verified'}]}
        def api(args, **kwargs):
            if args[1:3] == ['api', 'graphql']:
                return self.lookup({'databaseId': 123})
            return subprocess.CompletedProcess(args, 1, '', 'gh: Not Found (HTTP 404)')
        with patch.object(binary.subprocess, 'run', side_effect=api), patch.object(binary, 'gh', return_value=json.dumps(draft).encode()) as fetch:
            self.assertEqual(binary.release(self.info), draft)
        fetch.assert_called_once_with('api', 'repos/owner/example/releases/123')

    def test_graphql_null_is_an_absent_release(self):
        with patch.object(binary.subprocess, 'run', return_value=self.lookup(None)):
            self.assertIsNone(binary.release(self.info))

    def test_api_failure_is_never_treated_as_an_absent_draft(self):
        for error in ['gh: Forbidden (HTTP 403)', 'gh: Not Found (HTTP 404)']:
            with self.subTest(error=error), patch.object(binary.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', error)):
                with self.assertRaises(RuntimeError):
                    binary.release(self.info)

    def test_resolved_release_cannot_change_the_requested_tag(self):
        other = {'id': 123, 'tag_name': 'v9.9.9', 'draft': True, 'assets': []}
        with patch.object(binary.subprocess, 'run', return_value=self.lookup({'databaseId': 123})), patch.object(binary, 'gh', return_value=json.dumps(other).encode()):
            with self.assertRaises(ValueError):
                binary.release(self.info)


if __name__ == '__main__':
    unittest.main()
