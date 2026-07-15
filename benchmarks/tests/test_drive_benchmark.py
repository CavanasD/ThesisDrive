from __future__ import annotations

import csv
import hashlib
import json
import re
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from benchmarks.drive_benchmark import (
    MAX_CHUNK_SIZE,
    BenchmarkRunner,
    DataPlaneClient,
    Session,
    load_sessions,
    percentile,
    write_reports,
)


class FakeTransferState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.content = b""
        self.uploaded = bytearray()
        self.put_ranges: list[str] = []
        self.put_sizes: list[int] = []
        self.get_ranges: list[str] = []

    def reset(self, content: bytes) -> None:
        with self.lock:
            self.content = content
            self.uploaded = bytearray()
            self.put_ranges = []
            self.put_sizes = []
            self.get_ranges = []


STATE = FakeTransferState()


class FakeTransferHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == "Bearer test-ticket":
            return True
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if not self._authorized():
            return
        content_range = self.headers.get("Content-Range", "")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        with STATE.lock:
            STATE.put_ranges.append(content_range)
            STATE.put_sizes.append(len(body))
            if content_range == "bytes */0":
                start = end = total = 0
            else:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if not match:
                    self.send_error(400)
                    return
                start, inclusive_end, total = map(int, match.groups())
                end = inclusive_end + 1
                if start != len(STATE.uploaded) or len(body) != end - start:
                    self.send_error(409)
                    return
                STATE.uploaded.extend(body)
            completed = end == total
            offset = end
            digest = hashlib.sha256(STATE.uploaded).hexdigest()

        if completed:
            payload = json.dumps({"status": "completed", "sha256": digest}).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
        else:
            payload = b""
            self.send_response(204)
            self.send_header("Content-Length", "0")
        self.send_header("Upload-Offset", str(offset))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if not self._authorized():
            return
        range_header = self.headers.get("Range", "")
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", range_header)
        if not match:
            self.send_error(400)
            return
        start, end = map(int, match.groups())
        with STATE.lock:
            content = STATE.content
            STATE.get_ranges.append(range_header)
        if start < 0 or end >= len(content) or end < start:
            self.send_response(416)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = content[start:end + 1]
        self.send_response(206)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(content)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        pass


class DriveBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTransferHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.content = bytes((index * 17) % 251 for index in range(20_123))
        self.file = self.root / "fixture.bin"
        self.file.write_bytes(self.content)
        self.sha256 = hashlib.sha256(self.content).hexdigest()
        STATE.reset(self.content)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sessions(self) -> tuple[Session, Session]:
        upload = Session(
            "upload-test",
            "upload",
            f"{self.base_url}/api/v1/transfers/upload-test",
            "test-ticket",
            self.file,
            self.sha256,
            len(self.content),
        )
        download = Session(
            "download-test",
            "download",
            f"{self.base_url}/api/v1/transfers/download-test/content",
            "test-ticket",
            self.file,
            self.sha256,
            len(self.content),
        )
        return upload, download

    def test_content_range_upload_and_range_download_are_chunked_and_verified(self) -> None:
        upload, download = self.sessions()
        client = DataPlaneClient(chunk_size=4096, timeout=5)
        client.prepare([upload, download])

        upload_result = client.upload(upload)
        self.assertTrue(upload_result.success, upload_result.error)
        self.assertEqual(bytes(STATE.uploaded), self.content)
        self.assertLessEqual(max(STATE.put_sizes), 4096)
        self.assertEqual(STATE.put_ranges[0], f"bytes 0-4095/{len(self.content)}")

        download_result = client.download(download)
        self.assertTrue(download_result.success, download_result.error)
        self.assertEqual(download_result.sha256, self.sha256)
        self.assertEqual(STATE.get_ranges[0], "bytes=0-4095")
        range_lengths = [
            int(match.group(2)) - int(match.group(1)) + 1
            for value in STATE.get_ranges
            if (match := re.fullmatch(r"bytes=(\d+)-(\d+)", value))
        ]
        self.assertLessEqual(max(range_lengths), 4096)

    def test_load_sessions_and_concurrent_matrix_statistics(self) -> None:
        payload = {
            "sessions": [{
                "name": "download-fixture",
                "operation": "download",
                "download_url": f"{self.base_url}/download",
                "ticket": "test-ticket",
                "file": self.file.name,
                "size": len(self.content),
                "sha256": self.sha256,
            }],
        }
        sessions_path = self.root / "sessions.json"
        sessions_path.write_text(json.dumps(payload), encoding="utf-8")
        sessions = load_sessions(sessions_path)
        runner = BenchmarkRunner(DataPlaneClient(chunk_size=4096, timeout=5), sessions)

        batches, summaries = runner.run_matrix(
            ["download"], [2], repeats=2, warmup_seconds=0,
        )

        self.assertEqual(len(batches), 2)
        self.assertEqual(summaries[0]["attempts"], 4)
        self.assertEqual(summaries[0]["successes"], 4)
        self.assertEqual(summaries[0]["error_rate"], 0)
        self.assertGreater(summaries[0]["throughput_mib_s"], 0)
        self.assertGreaterEqual(summaries[0]["completion_p99_ms"], summaries[0]["completion_p50_ms"])

        json_path, csv_path = write_reports(
            self.root / "result", {"ticket": "not-recorded"}, batches, summaries,
        )
        report = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"][0]["attempts"], 4)
        self.assertEqual(report["config"]["ticket"], "[redacted]")
        self.assertNotIn("test-ticket", json_path.read_text(encoding="utf-8"))
        self.assertNotIn("not-recorded", json_path.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(rows[0]["concurrency"], "2")

    def test_empty_upload_uses_zero_length_content_range(self) -> None:
        empty = self.root / "empty.bin"
        empty.write_bytes(b"")
        STATE.reset(b"")
        session = Session(
            "empty", "upload", f"{self.base_url}/empty", "test-ticket", empty,
            hashlib.sha256(b"").hexdigest(), 0,
        )

        result = DataPlaneClient(chunk_size=4096, timeout=5).upload(session)

        self.assertTrue(result.success, result.error)
        self.assertEqual(STATE.put_ranges, ["bytes */0"])
        self.assertEqual(STATE.put_sizes, [0])

    def test_percentiles_and_chunk_limit(self) -> None:
        self.assertEqual(percentile([1], 0.99), 1)
        self.assertEqual(percentile([0, 10], 0.50), 5)
        self.assertGreater(percentile([1, 2, 3, 4], 0.95), 3)
        with self.assertRaises(ValueError):
            DataPlaneClient(chunk_size=MAX_CHUNK_SIZE + 1)


if __name__ == "__main__":
    unittest.main()
