"""Bootstrap must authenticate release lookups and never cache an unresolved latest."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).parents[1]
ACTION = ROOT / '.github/actions/setup-cargo-binstall/action.yml'


class ResolutionTests(unittest.TestCase):
    def run_resolution(self, mode):
        source = ACTION.read_text()
        body = source.split('      run: |\n', 1)[1].split('\n    - ', 1)[0]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            curl = root / 'curl'
            curl.write_text('''#!/usr/bin/env python3
import os,sys
if os.environ['TEST_CURL_MODE'] == 'error':
    sys.stderr.write('HTTP 403: API limit reached\\n')
    sys.exit(22)
if 'Authorization: Bearer test-fixture-token' not in sys.argv:
    sys.exit(22)
print('{"tag_name":"v1.25.3"}')
''')
            curl.chmod(0o755)
            output = root / 'output'
            result = subprocess.run(['bash', '--noprofile', '--norc', '-o', 'pipefail', '-c',
                                     textwrap.dedent(body)], text=True, capture_output=True,
                                    env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
                                         'GH_TOKEN': 'test-fixture-token', 'TEST_CURL_MODE': mode,
                                         'GITHUB_OUTPUT': str(output)})
            return result, output.read_text() if output.exists() else ''

    def test_authenticated_resolution_writes_a_concrete_version(self):
        result, output = self.run_resolution('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, 'version=v1.25.3\n')
        self.assertIn('GH_TOKEN: ${{ github.token }}', ACTION.read_text())

    def test_api_error_fails_without_a_coarse_cache_key(self):
        result, output = self.run_resolution('error')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, '')
        self.assertIn('HTTP 403', result.stderr)


if __name__ == '__main__':
    unittest.main()
