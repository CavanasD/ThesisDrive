#!/usr/bin/env python3
"""Bounded-memory HTTP upload/download benchmark for ThesisDrive."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import ssl
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MAX_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_CONCURRENCY = (1, 10, 20, 50)
ACCEPTED_UPLOAD_STATUSES = {200, 201, 204, 308}


@dataclass(frozen=True)
class Session:
    name: str
    operation: str
    url: str
    ticket: str
    file: Path
    expected_sha256: str = ""
    expected_size: int | None = None


@dataclass
class OperationResult:
    session: str
    operation: str
    success: bool
    transferred_bytes: int
    ttfb_seconds: float
    completion_seconds: float
    sha256: str = ""
    error: str = ""


@dataclass
class BatchResult:
    operation: str
    concurrency: int
    repeat: int
    wall_seconds: float
    results: list[OperationResult]


def percentile(values: Iterable[float], fraction: float) -> float:
    """Return a linearly interpolated percentile; works for one-item samples."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _session_operations(raw: dict[str, Any]) -> list[str]:
    operation = str(raw.get("operation", "")).strip().lower()
    if operation:
        if operation not in {"upload", "download"}:
            raise ValueError(f"unsupported operation: {operation}")
        return [operation]
    operations = []
    if raw.get("upload_url"):
        operations.append("upload")
    if raw.get("download_url"):
        operations.append("download")
    if not operations:
        raise ValueError("session requires operation or upload_url/download_url")
    return operations


def load_sessions(path: Path) -> list[Session]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sessions", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError("sessions JSON must contain a non-empty sessions array")

    sessions: list[Session] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"session #{index + 1} must be an object")
        file_value = raw.get("file")
        if not file_value:
            raise ValueError(f"session #{index + 1} requires file")
        file_path = Path(str(file_value))
        if not file_path.is_absolute():
            file_path = (path.parent / file_path).resolve()
        if not file_path.is_file():
            raise ValueError(f"session file not found: {file_path}")

        base_name = str(raw.get("name") or file_path.name)
        for operation in _session_operations(raw):
            url = str(raw.get(f"{operation}_url") or raw.get("url") or "").strip()
            ticket = str(raw.get(f"{operation}_ticket") or raw.get("ticket") or "").strip()
            if not url or not ticket:
                raise ValueError(f"{base_name}/{operation} requires URL and ticket")
            name = base_name if raw.get("operation") else f"{base_name}-{operation}"
            size = raw.get("size", raw.get("file_size"))
            sessions.append(Session(
                name=name,
                operation=operation,
                url=url,
                ticket=ticket,
                file=file_path,
                expected_sha256=str(raw.get("sha256") or "").lower(),
                expected_size=int(size) if size is not None else None,
            ))
    return sessions


class DataPlaneClient:
    def __init__(
        self,
        chunk_size: int = MAX_CHUNK_SIZE,
        timeout: float = 120.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError(f"chunk_size must be between 1 and {MAX_CHUNK_SIZE}")
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.ssl_context = ssl_context
        self._manifest_cache: dict[tuple[Path, int, int], tuple[int, str]] = {}
        self._manifest_lock = threading.Lock()

    def manifest(self, path: Path) -> tuple[int, str]:
        stat = path.stat()
        key = (path, stat.st_size, stat.st_mtime_ns)
        with self._manifest_lock:
            cached = self._manifest_cache.get(key)
            if cached:
                return cached
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(self.chunk_size):
                    digest.update(chunk)
            result = (stat.st_size, digest.hexdigest())
            self._manifest_cache[key] = result
            return result

    def prepare(self, sessions: Iterable[Session]) -> None:
        for session in sessions:
            size, digest = self.manifest(session.file)
            if session.expected_size is not None and session.expected_size != size:
                raise ValueError(f"{session.name}: configured size does not match file")
            if session.expected_sha256 and session.expected_sha256 != digest:
                raise ValueError(f"{session.name}: configured sha256 does not match file")

    def _open(self, request: urllib.request.Request):
        return urllib.request.urlopen(
            request,
            timeout=self.timeout,
            context=self.ssl_context,
        )

    @staticmethod
    def _headers(session: Session) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {session.ticket}",
            "User-Agent": "ThesisDrive-Benchmark/1.0",
        }

    def upload(self, session: Session) -> OperationResult:
        started = time.perf_counter()
        first_byte_at: float | None = None
        size, expected_digest = self.manifest(session.file)
        digest = hashlib.sha256()
        offset = 0
        final_payload: dict[str, Any] = {}

        try:
            with session.file.open("rb") as source:
                while True:
                    chunk = source.read(self.chunk_size)
                    if not chunk and (offset > 0 or size > 0):
                        break
                    end = offset + len(chunk)
                    digest.update(chunk)
                    headers = self._headers(session)
                    headers.update({
                        "Content-Type": "application/octet-stream",
                        "Content-Range": "bytes */0" if size == 0 else f"bytes {offset}-{end - 1}/{size}",
                        "Idempotency-Key": f"benchmark:{session.name}:{offset}:{end}",
                        "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
                    })
                    request = urllib.request.Request(session.url, data=chunk, headers=headers, method="PUT")
                    with self._open(request) as response:
                        if first_byte_at is None:
                            first_byte_at = time.perf_counter()
                        if response.status not in ACCEPTED_UPLOAD_STATUSES:
                            raise RuntimeError(f"upload returned HTTP {response.status}")
                        body = response.read(64 * 1024)
                        if body:
                            final_payload = json.loads(body.decode("utf-8"))
                        reported = response.headers.get("Upload-Offset")
                        if reported is not None and int(reported) != end:
                            raise RuntimeError(f"Upload-Offset {reported} does not match {end}")
                    offset = end
                    if size == 0:
                        break

            actual_digest = digest.hexdigest()
            if actual_digest != expected_digest:
                raise RuntimeError("local SHA-256 changed during upload")
            server_digest = str(final_payload.get("sha256") or "").lower()
            verification_digest = session.expected_sha256 or server_digest
            if not verification_digest:
                raise RuntimeError("upload response/session did not provide SHA-256 for verification")
            if verification_digest != actual_digest:
                raise RuntimeError("upload SHA-256 verification failed")
            completed = time.perf_counter()
            return OperationResult(
                session=session.name,
                operation="upload",
                success=True,
                transferred_bytes=size,
                ttfb_seconds=(first_byte_at or completed) - started,
                completion_seconds=completed - started,
                sha256=actual_digest,
            )
        except Exception as error:  # operation failures belong in the report
            completed = time.perf_counter()
            return OperationResult(
                session=session.name,
                operation="upload",
                success=False,
                transferred_bytes=0,
                ttfb_seconds=(first_byte_at - started) if first_byte_at else 0.0,
                completion_seconds=completed - started,
                error=f"{type(error).__name__}: {error}",
            )

    def download(self, session: Session) -> OperationResult:
        started = time.perf_counter()
        first_byte_at: float | None = None
        size, local_digest = self.manifest(session.file)
        expected_size = session.expected_size if session.expected_size is not None else size
        expected_digest = session.expected_sha256 or local_digest
        digest = hashlib.sha256()
        offset = 0

        try:
            while offset < expected_size:
                end = min(offset + self.chunk_size, expected_size) - 1
                headers = self._headers(session)
                headers["Range"] = f"bytes={offset}-{end}"
                request = urllib.request.Request(session.url, headers=headers, method="GET")
                with self._open(request) as response:
                    if first_byte_at is None:
                        first_byte_at = time.perf_counter()
                    if response.status != 206:
                        raise RuntimeError(f"range download returned HTTP {response.status}, expected 206")
                    content_range = response.headers.get("Content-Range", "")
                    expected_range = f"bytes {offset}-{end}/{expected_size}"
                    if content_range != expected_range:
                        raise RuntimeError(f"Content-Range {content_range!r} != {expected_range!r}")
                    received = 0
                    while piece := response.read(min(64 * 1024, end - offset + 1 - received)):
                        digest.update(piece)
                        received += len(piece)
                    if received != end - offset + 1:
                        raise RuntimeError("range response length mismatch")
                offset = end + 1

            actual_digest = digest.hexdigest()
            if actual_digest != expected_digest:
                raise RuntimeError("download SHA-256 verification failed")
            completed = time.perf_counter()
            return OperationResult(
                session=session.name,
                operation="download",
                success=True,
                transferred_bytes=expected_size,
                ttfb_seconds=(first_byte_at or completed) - started,
                completion_seconds=completed - started,
                sha256=actual_digest,
            )
        except Exception as error:  # operation failures belong in the report
            completed = time.perf_counter()
            return OperationResult(
                session=session.name,
                operation="download",
                success=False,
                transferred_bytes=0,
                ttfb_seconds=(first_byte_at - started) if first_byte_at else 0.0,
                completion_seconds=completed - started,
                error=f"{type(error).__name__}: {error}",
            )

    def run(self, session: Session) -> OperationResult:
        return self.upload(session) if session.operation == "upload" else self.download(session)


class BenchmarkRunner:
    def __init__(self, client: DataPlaneClient, sessions: list[Session]) -> None:
        self.client = client
        self.sessions = sessions

    def _batch(self, operation: str, concurrency: int, repeat: int) -> BatchResult:
        pool = [session for session in self.sessions if session.operation == operation]
        if not pool:
            raise ValueError(f"no {operation} sessions configured")
        jobs = [pool[index % len(pool)] for index in range(concurrency)]
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="drive-bench") as executor:
            futures = [executor.submit(self.client.run, session) for session in jobs]
            results = [future.result() for future in as_completed(futures)]
        return BatchResult(operation, concurrency, repeat, time.perf_counter() - started, results)

    def warmup(self, operation: str, concurrency: int, seconds: float) -> None:
        if seconds <= 0:
            return
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            self._batch(operation, concurrency, repeat=-1)

    def run_matrix(
        self,
        operations: Iterable[str],
        concurrencies: Iterable[int],
        repeats: int = 3,
        warmup_seconds: float = 0,
    ) -> tuple[list[BatchResult], list[dict[str, Any]]]:
        batches: list[BatchResult] = []
        for operation in operations:
            candidates = [s for s in self.sessions if s.operation == operation]
            self.client.prepare(candidates)
            for concurrency in concurrencies:
                self.warmup(operation, concurrency, warmup_seconds)
                for repeat in range(1, repeats + 1):
                    batches.append(self._batch(operation, concurrency, repeat))
        return batches, summarize(batches)


def summarize(batches: Iterable[BatchResult]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[BatchResult]] = {}
    for batch in batches:
        groups.setdefault((batch.operation, batch.concurrency), []).append(batch)

    summaries = []
    for (operation, concurrency), grouped in sorted(groups.items()):
        results = [result for batch in grouped for result in batch.results]
        successes = [result for result in results if result.success]
        total_wall = sum(batch.wall_seconds for batch in grouped)
        successful_bytes = sum(result.transferred_bytes for result in successes)
        completions = [result.completion_seconds for result in successes]
        ttfbs = [result.ttfb_seconds for result in successes]
        summaries.append({
            "operation": operation,
            "concurrency": concurrency,
            "repeats": len(grouped),
            "attempts": len(results),
            "successes": len(successes),
            "errors": len(results) - len(successes),
            "error_rate": (len(results) - len(successes)) / len(results) if results else 0.0,
            "throughput_mib_s": successful_bytes / (1024 * 1024) / total_wall if total_wall else 0.0,
            "ttfb_p50_ms": percentile(ttfbs, 0.50) * 1000,
            "ttfb_p95_ms": percentile(ttfbs, 0.95) * 1000,
            "ttfb_p99_ms": percentile(ttfbs, 0.99) * 1000,
            "completion_p50_ms": percentile(completions, 0.50) * 1000,
            "completion_p95_ms": percentile(completions, 0.95) * 1000,
            "completion_p99_ms": percentile(completions, 0.99) * 1000,
        })
    return summaries


def write_reports(
    prefix: Path,
    config: dict[str, Any],
    batches: list[BatchResult],
    summaries: list[dict[str, Any]],
) -> tuple[Path, Path]:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": _redact_sensitive(config),
        "summary": summaries,
        "batches": [
            {
                "operation": batch.operation,
                "concurrency": batch.concurrency,
                "repeat": batch.repeat,
                "wall_seconds": batch.wall_seconds,
                "results": [asdict(result) for result in batch.results],
            }
            for batch in batches
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = list(summaries[0].keys()) if summaries else []
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            writer.writerows(summaries)
    return json_path, csv_path


def _redact_sensitive(value: Any) -> Any:
    """Defense-in-depth: report helpers never serialize credentials or URLs."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("ticket", "token", "authorization", "url")):
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = _redact_sensitive(item)
        return sanitized
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive(item) for item in value]
    return value


def parse_concurrencies(value: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("concurrency must be positive comma-separated integers")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True, help="prepared transfer sessions JSON")
    parser.add_argument("--operations", choices=("upload", "download", "both"), default="both")
    parser.add_argument("--concurrency", type=parse_concurrencies, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup-seconds", type=float, default=15.0)
    parser.add_argument("--chunk-size", type=int, default=MAX_CHUNK_SIZE)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--ca-file", type=Path, help="custom CA bundle for HTTPS")
    parser.add_argument("--output-prefix", type=Path, help="report path without extension")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeats <= 0 or args.warmup_seconds < 0:
        raise SystemExit("repeats must be positive and warmup-seconds cannot be negative")
    sessions = load_sessions(args.sessions.resolve())
    operations = ("upload", "download") if args.operations == "both" else (args.operations,)
    ssl_context = ssl.create_default_context(cafile=str(args.ca_file)) if args.ca_file else None
    client = DataPlaneClient(args.chunk_size, args.timeout, ssl_context)
    runner = BenchmarkRunner(client, sessions)
    batches, summaries = runner.run_matrix(
        operations,
        args.concurrency,
        repeats=args.repeats,
        warmup_seconds=args.warmup_seconds,
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = args.output_prefix or Path(__file__).parent / "results" / f"drive-benchmark-{stamp}"
    config = {
        "sessions": str(args.sessions),
        "operations": list(operations),
        "concurrency": list(args.concurrency),
        "repeats": args.repeats,
        "warmup_seconds": args.warmup_seconds,
        "chunk_size": args.chunk_size,
        "timeout": args.timeout,
    }
    json_path, csv_path = write_reports(prefix, config, batches, summaries)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
