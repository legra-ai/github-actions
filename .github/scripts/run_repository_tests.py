"""Run repository Python policy tests, including hyphenated script names."""
import importlib.util
from pathlib import Path
import sys
import unittest


def main():
    scripts = Path('scripts').resolve()
    sys.path.insert(0, str(scripts))
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    # bounded: checked-in repository policy scripts, not application datasets.
    for index, path in enumerate(sorted(scripts.glob('test*.py'))):
        spec = importlib.util.spec_from_file_location(f'repository_policy_{index}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    if suite.countTestCases() == 0:
        raise RuntimeError('No repository policy tests found')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
