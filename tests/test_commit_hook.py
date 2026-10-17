"""The local hook must validate the first scoped Conventional Commit header."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommitHookTests(unittest.TestCase):
    def test_scoped_breaking_headers_and_invalid_first_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cog = root / 'cog'
            cog.write_text('#!/bin/sh\nexit 0\n', newline='\n')
            cog.chmod(0o755)
            message = root / 'message'
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH']}
            shell = ((Path(subprocess.check_output(['git', '--exec-path'], text=True).strip()).parents[2]
                      / 'bin/bash.exe') if os.name == 'nt' else 'bash')
            for header, body, expected in [
                ('fix(merger)!: require a dedicated identity', '', 0),
                ('fix(merger): enforce strict checks', '', 0),
                ('build(deps): update package', '', 0),
                ('ci(deps-dev): update action', '', 0),
                ('fix: missing scope', '\nfix(ci): forged body\n', 1),
                ('oops(ci): invalid type', '', 1),
                ('fix(ci): ', '', 1),
            ]:
                with self.subTest(header=header):
                    message.write_text(header + '\n' + body, newline='\n')
                    result = subprocess.run([str(shell), str(ROOT / '.githooks/commit-msg'), str(message)],
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
