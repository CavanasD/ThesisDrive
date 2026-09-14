"""Run the upstream managed harness in an explicitly disposable linked worktree."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases = [('server-info', 0), ('auth-read', 0), ('upload-unique', 1), ('download', 1), ('upload-unique', 8), ('download', 8)]
    for scenario, mib in cases:
        for users in (1, 4, 10):
            for repeat in (1, 2, 3):
                stem = f'{scenario}-{mib}MiB-c{users}-r{repeat}'
                output = args.output_dir / (stem + '.json')
                command = [sys.executable, '-m', 'tests.stress.ws_load', '--scenario', scenario, '--users', str(users), '--duration', '5s', '--payload-size', str(max(1, mib) * 1024**2), '--managed-reset', '--output', str(output.resolve())]
                with (args.output_dir / (stem + '.log')).open('w', encoding='utf-8') as log:
                    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                print(stem, result.returncode, flush=True)
                if result.returncode:
                    raise RuntimeError(f'Failed case: {stem}; inspect its log')
                report = json.loads(output.read_text(encoding='utf-8'))
                print('requests', report['requests'], 'errors', report['errors'], flush=True)


if __name__ == '__main__':
    main()
