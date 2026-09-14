"""Authenticated control and byte-transfer evaluation on a disposable CFMS instance."""

import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import random
import secrets
import ssl
import statistics
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect


class Client:
    loop = None

    def __init__(self, args):
        if Client.loop is None:
            Client.loop = asyncio.new_event_loop()
            threading.Thread(target=Client.loop.run_forever, daemon=True).start()
        context = ssl.create_default_context(cafile=args.ca_file) if args.ws_url.startswith("wss:") else None
        async def open_connection():
            return await connect(args.ws_url, ssl=context, proxy=None, origin=args.origin, open_timeout=30)
        self.ws = asyncio.run_coroutine_threadsafe(open_connection(), self.loop).result(timeout=35)
        self.frame = 1
        self.auth = {}
        login = self.request("login", {"username": "admin", "password": Path(args.password_file).read_text().strip()})
        self.auth = {"username": "admin", "token": login["token"]}

    def request(self, action, data):
        return asyncio.run_coroutine_threadsafe(self._request(action, data), self.loop).result(timeout=35)

    async def _request(self, action, data):
        identifier = self.frame
        self.frame += 2
        envelope = dict(action=action, data=data, **self.auth)
        if self.auth:
            envelope.update(nonce=secrets.token_hex(16), timestamp=time.time())
        await self.ws.send(struct.pack(">IB", identifier, 0) + json.dumps(envelope).encode())
        while True:
            frame = await asyncio.wait_for(self.ws.recv(), timeout=30)
            if struct.unpack(">I", frame[:4])[0] == identifier and frame[4] == 1:
                response = json.loads(frame[5:])
                if response["code"] != 200:
                    raise RuntimeError(f"{action}: code {response['code']}")
                return response["data"]

    def close(self):
        asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop).result(timeout=15)


def percentiles(values):
    ordered = sorted(values)
    def quantile(p):
        rank = (len(ordered) - 1) * p
        lower = int(rank)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (rank - lower)
    return {"mean_ms": statistics.mean(values), "p50_ms": quantile(.5), "p95_ms": quantile(.95), "p99_ms": quantile(.99)} if values else {}


def control_round(args, action, data, concurrency):
    barrier = threading.Barrier(concurrency)
    clients = [Client(args) for _ in range(concurrency)]
    def worker(client):
        try:
            warmup_errors = []
            for _ in range(5):
                try:
                    client.request(action, data)
                except Exception as exc:
                    warmup_errors.append(str(exc))
            barrier.wait(timeout=60)
            start = time.perf_counter()
            samples, errors = [], []
            for _ in range(args.requests):
                begin = time.perf_counter()
                try:
                    client.request(action, data)
                    samples.append((time.perf_counter() - begin) * 1000)
                except Exception as exc:
                    errors.append(str(exc))
            return start, time.perf_counter(), samples, errors, warmup_errors
        finally:
            client.close()
    with concurrent.futures.ThreadPoolExecutor(concurrency) as pool:
        rows = list(pool.map(worker, clients))
    elapsed = max(r[1] for r in rows) - min(r[0] for r in rows)
    latencies = [n for r in rows for n in r[2]]
    errors = [e for r in rows for e in r[3]]
    return dict(action=action, concurrency=concurrency, attempts=concurrency*args.requests, successes=len(latencies), elapsed_seconds=elapsed, throughput_rps=len(latencies)/elapsed, errors=errors, warmup_errors=[e for r in rows for e in r[4]], latencies_ms=latencies, **percentiles(latencies))


def transfer(args, session, fixture, operation):
    size = fixture.stat().st_size
    task = session['task_id']
    url = args.http_base.rstrip('/') + f'/api/v1/transfers/{task}' + ('/content' if operation == 'download' else '')
    headers = {'Authorization': 'Bearer ' + session['ticket']}
    digest = hashlib.sha256()
    offset = 0
    start = time.perf_counter()
    first_response_ms = None
    with fixture.open('rb') as source:
        while offset < size or (size == 0 and offset == 0):
            count = min(8 * 1024**2, size-offset)
            request_headers = dict(headers)
            if operation == 'upload':
                payload = source.read(count)
                request_headers.update({'Content-Range': f'bytes {offset}-{offset+count-1}/{size}' if size else 'bytes */0', 'Content-Type': 'application/octet-stream'})
                request = urllib.request.Request(url, data=payload, method='PUT', headers=request_headers)
            else:
                if size:
                    request_headers['Range'] = f'bytes={offset}-{offset+count-1}'
                request = urllib.request.Request(url, headers=request_headers)
            context = ssl.create_default_context(cafile=args.http_ca_file) if url.startswith('https:') else None
            with urllib.request.urlopen(request, timeout=60, context=context) as response:
                if first_response_ms is None:
                    first_response_ms = (time.perf_counter()-start)*1000
                if operation == 'download':
                    received = 0
                    while chunk := response.read(65536):
                        digest.update(chunk)
                        received += len(chunk)
                    assert received == count, 'download size mismatch'
                else:
                    body = response.read()
                    result = json.loads(body) if body else {}
                    confirmed = int(response.headers.get('Upload-Offset', result.get('offset', result.get('size', -1))))
                    assert confirmed == offset+count, 'upload offset mismatch'
                    if offset+count == size:
                        assert result.get('sha256') == session['sha256'], 'upload digest mismatch'
            offset += count
            if size == 0:
                break
    if operation == 'download':
        assert digest.hexdigest() == session['sha256'], 'readback SHA-256 mismatch'
    return dict(size=size, completion_ms=(time.perf_counter()-start)*1000, first_response_ms=first_response_ms, sha256_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ws-url', required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--password-file', required=True)
    parser.add_argument('--origin')
    parser.add_argument('--http-base', default='http://transfer-data-plane:8082')
    parser.add_argument('--http-ca-file')
    parser.add_argument('--mode', choices=['controls', 'transfers'], required=True)
    parser.add_argument('--concurrency', default='1,4,10')
    parser.add_argument('--sizes-mib', default='1,8,32')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--requests', type=int, default=40)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    client = Client(args)
    rows = []
    report = dict(mode=args.mode, started_at=time.time(), repeats=args.repeats, requests_per_worker=args.requests, source_commit='ddcfd50 plus thesis integration working tree', results=rows)
    label = 'eval-' + secrets.token_hex(6)
    parent = client.request('create_directory', {'name': label, 'parent_id': '/'})['id']
    report['server'] = client.request('server_info', {})
    report['fixture_directory_id'] = parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        if args.mode == 'controls':
            for i in range(250):
                client.request('create_directory', {'name': f'{label}-BenchmarkSearch-{i:04}', 'parent_id': parent})
            actions = [('server_info', {}), ('list_directory', {'folder_id': parent, 'page_size': 128}), ('search', {'query': label+'-BenchmarkSearch', 'search_documents': False, 'search_directories': True, 'page_size': 128})]
            report['search_fixture_count'] = 250
            probe = client.request(*actions[-1])
            report['search_first_page_items'] = len(probe['items'])
            assert len(probe['items']) == 128, 'search fixture page is not populated'
            for action, data in actions:
                for concurrency in map(int, args.concurrency.split(',')):
                    for repeat in range(args.repeats):
                        row = control_round(args, action, data, concurrency)
                        row['repeat'] = repeat+1
                        rows.append(row)
                        save()
                        print(action, concurrency, repeat+1, row['successes'], flush=True)
        else:
            for mib in map(int, args.sizes_mib.split(',')):
                fixture = args.output.parent / f'{label}-{mib}MiB.bin'
                rng = random.Random(20260908+mib)
                with fixture.open('wb') as output:
                    for _ in range(mib):
                        output.write(rng.randbytes(1024**2))
                with fixture.open('rb') as source:
                    digest = hashlib.file_digest(source, 'sha256').hexdigest()
                for concurrency in map(int, args.concurrency.split(',')):
                    for repeat in range(args.repeats):
                        documents, uploads = [], []
                        for worker in range(concurrency):
                            document = client.request('create_document', {'title':f'{mib}-{concurrency}-{repeat}-{worker}.bin', 'folder_id': parent})
                            documents.append(document['document_id'])
                            task = document['task_data']['task_id']
                            upload = client.request('prepare_upload', {'task_id':task,'size':fixture.stat().st_size,'sha256':digest,'filename':'benchmark.bin','content_type':'application/octet-stream'})
                            uploads.append(dict(upload, task_id=task, sha256=digest))
                        for operation in ['upload','download']:
                            sessions = uploads
                            if operation == 'download':
                                sessions = []
                                for identifier in documents:
                                    task = client.request('get_document', {'document_id': identifier})['task_data']['task_id']
                                    sessions.append(dict(client.request('prepare_download', {'task_id':task}),task_id=task,sha256=digest))
                            begin = time.perf_counter()
                            with concurrent.futures.ThreadPoolExecutor(concurrency) as pool:
                                results = list(pool.map(lambda session: transfer(args,session,fixture,operation),sessions))
                            elapsed = time.perf_counter()-begin
                            row = dict(operation=operation,size_mib=mib,concurrency=concurrency,repeat=repeat+1,elapsed_seconds=elapsed,throughput_mib_s=mib*concurrency/elapsed,files=results)
                            rows.append(row)
                            save()
                            for session in sessions if operation == 'upload' else []:
                                deadline = time.monotonic()+30
                                while client.request('get_transfer_status', {'task_id':session['task_id']})['status'] != 'completed':
                                    if time.monotonic() > deadline:
                                        raise TimeoutError('Core completion not confirmed')
                                    time.sleep(.05)
                            if operation == 'upload':
                                row['business_confirmed_ms'] = (time.perf_counter()-begin)*1000
                            else:
                                row['server_status_after_readback'] = [client.request('get_transfer_status', {'task_id':s['task_id']})['status'] for s in sessions]
                            save()
                            print(operation,mib,concurrency,repeat+1,flush=True)
                        for identifier in documents:
                            client.request('delete_document', {'document_id':identifier})
                            client.request('purge_document', {'document_id':identifier})
                fixture.unlink()
        report['completed_at'] = time.time()
    except Exception as exc:
        report['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        save()
        client.close()


if __name__ == '__main__':
    main()
