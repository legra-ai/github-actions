"""Keep executable release policy outside every Cargo source selection."""
import os
from pathlib import Path
import shutil


def main():
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    source = workspace / '.release-policy'
    destination = Path(os.environ['RUNNER_TEMP']).resolve(strict=True) / 'release-policy'
    if destination.is_relative_to(workspace):
        raise ValueError('Runner staging must be outside the source checkout')
    if source.is_symlink() or not source.is_dir() or destination.exists():
        raise ValueError('Unexpected policy checkout or occupied staging directory')
    shutil.move(str(source), str(destination))
    with open(os.environ['GITHUB_ENV'], 'a') as output:
        output.write(f'POLICY_ROOT={destination.as_posix()}\n')


if __name__ == '__main__':
    main()
