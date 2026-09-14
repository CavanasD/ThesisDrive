"""Scope-aware upstream load harness; run only in a disposable linked worktree."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path.cwd()))
from tomlkit import dumps, parse
from tests.stress import ws_load as load

if os.environ.get('BARE_TRACE_OUT'):
    import subprocess
    original_popen = subprocess.Popen

    def diagnostic_popen(command, *args, **kwargs):
        if isinstance(command, list) and command[1:] == ['main.py']:
            command = [command[0], '/bench/bare_trace_server.py']
        return original_popen(command, *args, **kwargs)

    subprocess.Popen = diagnostic_popen

profile = os.environ.get('BARE_POLICY', 'default')
assert profile in {'default', 'expanded'}
original_config = load.write_test_config
original_send = load.CFMSTestClient.send_request
original_phase = load.run_worker_phase
original_login = load.login_client
policy_snapshot = {}
active_workers = 0
responses = Counter()
latencies = []
examples = {}
login_gate = None


async def staged_login(*args, **kwargs):
    global login_gate
    if login_gate is None:
        login_gate = asyncio.Semaphore(2)
    async with login_gate:
        return await original_login(*args, **kwargs)


def write_config(*args, **kwargs):
    settings = original_config(*args, **kwargs)
    config = parse(settings.config_path.read_text(encoding='utf-8'))
    admission = config['server']['admission_control']
    if profile == 'expanded':
        admission['max_connections'] = 128
        admission['max_connections_per_ip'] = 128
        admission['max_inflight_requests'] = 128
    policy_snapshot.update(dict(admission))
    settings.config_path.write_text(dumps(config), encoding='utf-8')
    return settings


async def send_request(self, action, *args, **kwargs):
    measured = active_workers > 0
    started = time.perf_counter()
    response = await original_send(self, action, *args, **kwargs)
    if measured:
        code = response.get('code')
        data = response.get('data') or {}
        scope = data.get('scope', 'unspecified') if isinstance(data, dict) else 'unspecified'
        key = str(code) if code == 200 else f'{code}:{scope}'
        responses[key] += 1
        if code == 200:
            latencies.append((time.perf_counter() - started) * 1000)
        elif key not in examples:
            examples[key] = {'action': action, 'code': code, 'scope': scope,
                             'message': response.get('message'),
                             'retry_after_seconds': data.get('retry_after_seconds')}
    return response


async def run_phase(*args, **kwargs):
    global active_workers
    active_workers += 1
    try:
        return await original_phase(*args, **kwargs)
    finally:
        active_workers -= 1


load.write_test_config = write_config
load.CFMSTestClient.send_request = send_request
load.run_worker_phase = run_phase
if profile == 'expanded':
    load.login_client = staged_login
args = load.parse_args()
result = asyncio.run(load.run_load(args))
result['supplement'] = {
    'policy_profile': profile, 'admission_control': policy_snapshot,
    'setup_login_concurrency': 2 if profile == 'expanded' else args.users,
    'measurement_responses': dict(responses), 'rejection_examples': examples,
    'success_latencies_ms': latencies,
    'source_commit': 'a0041424e5b184f701fa7250c2f1535caa30afc7',
    'note': 'Upstream server source unchanged. Only expanded profile changes three admission limits. Client and server share the 2 CPU / 1 GiB container.',
}
load._write_result(args.output, result)
print(json.dumps({'users': args.users, 'scenario': args.scenario,
                  'policy': profile, 'responses': dict(responses),
                  'generator_health': result.get('generator_health')}, ensure_ascii=False), flush=True)
