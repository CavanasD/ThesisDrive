"""Sequential extended bare-server matrix, isolated from deployed services."""
import os
import json
from pathlib import Path
import subprocess
import sys

output = Path('/bench/extended')
output.mkdir(exist_ok=True)
cases = [('default', s, c, 0) for s in ('server-info', 'auth-read') for c in (10, 16)]
cases += [('expanded', s, c, 0) for s in ('server-info', 'auth-read') for c in (10, 32, 64)]
cases += [('default', 'server-info', 10, 50), ('expanded', 'server-info', 64, 50)]
for policy, scenario, users, rate in cases:
    for repeat in (1, 2, 3):
        stem = f'{policy}-{scenario}-c{users}-rate{rate}-r{repeat}'
        path = output / (stem + '.json')
        if path.exists() or (output / (stem + '.setup-failure.json')).exists():
            continue
        cmd = [sys.executable, '/bench/bare_extended.py', '--scenario', scenario,
               '--users', str(users), '--duration', '20s', '--rate', str(rate),
               '--managed-reset', '--output', str(path)]
        with (output / (stem + '.log')).open('w') as log:
            run = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                 env={**os.environ, 'BARE_POLICY': policy}, timeout=150)
        print(stem, run.returncode, flush=True)
        if run.returncode:
            (output / (stem + '.setup-failure.json')).write_text(json.dumps({
                'policy': policy, 'scenario': scenario, 'users': users,
                'rate': rate, 'repeat': repeat, 'exit_code': run.returncode,
                'note': 'Run did not reach a completed measured phase; see paired log. Excluded from measured throughput.'
            }))
