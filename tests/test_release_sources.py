"""Exercise real public-artifact acceptance and error handling without publishing."""

from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ACTION = Path(__file__).parents[1] / '.github/actions/monitor-release'
sys.path.insert(0, str(ACTION))
from release_health import Inspector
from release_http import API


class ArtifactAPI:
    def __init__(self):
        self.metadata = {}
        self.blobs = {}

    def json(self, url):
        return self.metadata[url]

    def github(self, path):
        return {'object': {'type': 'commit', 'sha': 'a' * 40}}

    @contextmanager
    def download(self, url):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'download'
            blob = self.blobs[url]
            path.write_bytes(blob)
            yield path, hashlib.sha256(blob).hexdigest()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.api = ArtifactAPI()
        self.checker = Inspector(self.api, {
            'repository': 'owner/example', 'workflow': 'ci.yml',
            'cli_assets': ['example-target.zip'],
        })

    def test_absent_npm_version_is_not_a_healthy_release(self):
        self.api.metadata['https://registry.npmjs.org/%40example%2Fnode/1.2.3'] = None
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.checker.check_npm('@example/node', '1.2.3', None)

    def test_npm_archive_bytes_must_match_preserved_release(self):
        self.api.metadata['https://registry.npmjs.org/example/1.2.3'] = {
            'version': '1.2.3', 'dist': {'tarball': 'https://example/npm'}}
        self.api.blobs['https://example/npm'] = b'different npm archive'
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.checker.check_npm('example', '1.2.3', {'files': {'example.tgz': '0' * 64}})

    def test_pypi_must_have_every_preserved_platform_wheel(self):
        self.api.metadata['https://pypi.org/pypi/example/1.2.3/json'] = {
            'info': {'version': '1.2.3'}, 'urls': []}
        with self.assertRaisesRegex(ValueError, 'Missing.*wheel'):
            self.checker.check_pypi('example', '1.2.3', {'files': {'example.whl': '0' * 64}})

    def test_pypi_download_is_checked_beyond_registry_metadata(self):
        self.api.metadata['https://pypi.org/pypi/example/1.2.3/json'] = {
            'info': {'version': '1.2.3'}, 'urls': [{'filename': 'example.whl',
                'digests': {'sha256': '0' * 64}, 'url': 'https://example/wheel'}]}
        self.api.blobs['https://example/wheel'] = b'changed download'
        with self.assertRaisesRegex(ValueError, 'download differs'):
            self.checker.check_pypi('example', '1.2.3', {'files': {'example.whl': '0' * 64}})

    def test_cli_download_must_match_asset_digest(self):
        self.api.blobs['https://example/cli'] = b'changed binary'
        release = {'draft': False, 'assets': [{'name': 'example-target.zip',
            'state': 'uploaded', 'digest': 'sha256:' + '0' * 64,
            'browser_download_url': 'https://example/cli'}]}
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.checker.check_cli('1.2.3', release)

    def test_crate_source_must_match_release_tag(self):
        self.api.metadata['https://crates.io/api/v1/crates/example/1.2.3'] = {'version': {'num': '1.2.3'}}
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            identity = json.dumps({'git': {'sha1': 'b' * 40}}).encode()
            member = tarfile.TarInfo('example-1.2.3/.cargo_vcs_info.json')
            member.size = len(identity)
            archive.addfile(member, io.BytesIO(identity))
        self.api.blobs['https://crates.io/api/v1/crates/example/1.2.3/download'] = buffer.getvalue()
        with self.assertRaisesRegex(ValueError, 'source differs'):
            self.checker.check_crates('example', '1.2.3', None)


class HTTPTests(unittest.TestCase):
    def test_registry_requests_never_receive_github_credentials(self):
        response = io.BytesIO(b'{"version":"1.2.3"}')
        with patch('release_http.urlopen', return_value=response) as request:
            API('secret-test-token').json('https://registry.example/package')
        self.assertFalse(request.call_args.args[0].has_header('Authorization'))

    def test_only_404_is_treated_as_missing(self):
        for code in [401, 403, 429, 500]:
            with self.subTest(code=code), patch('release_http.urlopen', side_effect=HTTPError(
                    'https://registry.example/package', code, 'failed', {}, io.BytesIO())):
                with self.assertRaisesRegex(RuntimeError, str(code)):
                    API('token').json('https://registry.example/package')

    def test_download_errors_are_explicit_and_do_not_leak_response_bodies(self):
        with patch('release_http.urlopen', side_effect=HTTPError(
                'https://example/archive', 403, 'secret response', {}, io.BytesIO())):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                with API('token').download('https://example/archive'):
                    self.fail('a failed download must not yield an artifact')


if __name__ == '__main__':
    unittest.main()
