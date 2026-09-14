"""Aggregate completed measurement phases; keep setup failures separate."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'benchmarks/records/2026-09-08/server-bare-extended'
groups = defaultdict(list)
failures = []
for path in sorted(DATA.glob('*.json')):
    if path.name.startswith('summary') or path.name.startswith('trace'):
        continue
    value = json.loads(path.read_text(encoding='utf-8'))
    if path.name.endswith('.setup-failure.json'):
        failures.append(value)
        continue
    if 'supplement' not in value:
        continue
    sup = value['supplement']
    phase = value['phases'][0]
    assert sum(sup['measurement_responses'].values()) == phase['requests'], path
    assert sup['measurement_responses'].get('200', 0) == phase['successes'], path
    groups[(sup['policy_profile'], value['scenario'], value['users'], phase['rate'])].append(value)

def quantile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index); high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)

rows = []
for (policy, scenario, users, rate), runs in sorted(groups.items()):
    elapsed = sum(r['phases'][0]['elapsed_seconds'] for r in runs)
    attempts = sum(r['phases'][0]['requests'] for r in runs)
    successes = sum(r['phases'][0]['successes'] for r in runs)
    latencies = [v for r in runs for v in r['supplement']['success_latencies_ms']]
    responses = Counter()
    for r in runs: responses.update(r['supplement']['measurement_responses'])
    rps = [r['phases'][0]['successes'] / r['phases'][0]['elapsed_seconds'] for r in runs]
    rows.append({'policy': policy, 'scenario': scenario, 'concurrency': users,
                 'rate': rate, 'repeats': len(runs), 'attempts': attempts,
                 'successes': successes, 'elapsed_seconds': elapsed,
                 'success_rps': successes / elapsed, 'rps_min': min(rps), 'rps_max': max(rps),
                 'error_rate': 1 - successes / attempts,
                 'p50_ms': quantile(latencies, .5), 'p95_ms': quantile(latencies, .95),
                 'p99_ms': quantile(latencies, .99), 'responses': dict(responses),
                 'generator_saturated': any(r['generator']['generator_saturated'] for r in runs),
                 'generator_lag_p99_max_ms': max(r['generator']['event_loop_lag_ms']['p99'] for r in runs),
                 'connection_errors': [r['connections']['errors'] for r in runs if r['connections']['errors']],
                 'dropped_iterations': sum(r['phases'][0]['dropped_iterations'] for r in runs)})
result = {'groups': rows, 'setup_failures': failures,
          'completed_runs': sum(r['repeats'] for r in rows),
          'note': 'Twenty-second measured phases, three repeats per completed group. Success-only pooled latency quantiles. Client/server colocated in a 2 CPU / 1 GiB container; no maximum-capacity claim.'}
(DATA/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
if rows:
    with (DATA/'summary.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
for row in rows:
    print(row['policy'], row['scenario'], row['concurrency'], row['rate'], row['repeats'],
          f"{row['success_rps']:.2f} rps; success {1-row['error_rate']:.2%}; p95 {row['p95_ms']:.2f} ms")
print('completed_runs', result['completed_runs'], 'setup_failures', len(failures))
