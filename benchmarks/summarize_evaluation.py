"""Summarize measured evaluation records without discarding failed requests."""

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / 'benchmarks/records/2026-09-08'


def quantile(values, fraction):
    values = sorted(values)
    rank = (len(values)-1)*fraction
    lo = int(rank)
    return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(rank-lo)


def summarize():
    native, controls, transfers = [], [], []
    for environment in ('local-bare','server-bare'):
        groups = defaultdict(list)
        for file in (RECORDS/environment).glob('*.json'):
            data = json.loads(file.read_text(encoding='utf-8'))
            mib = int(file.name.split('MiB')[0].rsplit('-',1)[1])
            groups[data['scenario'],mib,data['users']].append(data)
        for (scenario,mib,users), rows in sorted(groups.items()):
            attempts = sum(r['requests'] for r in rows)
            successes = sum(r['successes'] for r in rows)
            duration = sum(r['elapsed_seconds'] for r in rows)
            native.append(dict(environment=environment,scenario=scenario,size_mib=mib,concurrency=users,repeats=len(rows),attempts=attempts,successes=successes,error_rate=1-successes/attempts,throughput_rps=successes/duration,p95_mean_ms=statistics.mean(r['latency_ms']['p95'] for r in rows),rps_min=min(r['successes']/r['elapsed_seconds'] for r in rows),rps_max=max(r['successes']/r['elapsed_seconds'] for r in rows)))
    for filename in ('core-direct-final','full-controls','full-transfers'):
        path=RECORDS/'server-system'/(filename+'.json')
        if not path.exists():
            continue
        data=json.loads(path.read_text(encoding='utf-8'))
        groups=defaultdict(list)
        for row in data['results']:
            groups[row.get('action',row.get('operation')),row.get('size_mib',0),row['concurrency']].append(row)
        for (action,mib,users),rows in groups.items():
            if data['mode']=='controls':
                values=[v for row in rows for v in row['latencies_ms']]
                attempts=sum(row['attempts'] for row in rows)
                success=sum(row['successes'] for row in rows)
                controls.append(dict(path=filename,action=action,concurrency=users,repeats=len(rows),attempts=attempts,successes=success,error_rate=1-success/attempts,throughput_rps=success/sum(row['elapsed_seconds'] for row in rows),mean_ms=statistics.mean(values) if values else None,p50_ms=quantile(values,.5) if values else None,p95_ms=quantile(values,.95) if values else None,p99_ms=quantile(values,.99) if values else None))
            else:
                files=[f for row in rows for f in row['files']]
                completed=sum(f['sha256_ok'] for f in files)
                business=sum(len(r['files']) for r in rows if 'business_confirmed_ms' in r)
                transfers.append(dict(operation=action,size_mib=mib,concurrency=users,repeats=len(rows),files=len(files),sha256_passed=completed,business_confirmed=business if action=='upload' else None,throughput_mib_s=mib*completed/sum(r['elapsed_seconds'] for r in rows),completion_mean_ms=statistics.mean(f['completion_ms'] for f in files),completion_p95_ms=quantile([f['completion_ms'] for f in files],.95),rps_min=min(r['throughput_mib_s'] for r in rows),rps_max=max(r['throughput_mib_s'] for r in rows)))
    summary=dict(native=native,controls=controls,transfers=transfers)
    (RECORDS/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,rows in summary.items():
        if rows:
            with (RECORDS/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return summary


if __name__=='__main__':
    summary=summarize()
    print({name:len(rows) for name,rows in summary.items()})
