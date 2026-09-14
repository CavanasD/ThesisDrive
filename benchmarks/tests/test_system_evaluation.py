import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from benchmarks.system_evaluation import transfer


class UploadResponseTest(unittest.TestCase):
    def test_intermediate_204_and_final_201_are_both_accepted(self):
        payload = b'x' * (9 * 1024**2)
        digest = hashlib.sha256(payload).hexdigest()
        received = bytearray()

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                received.extend(self.rfile.read(int(self.headers['Content-Length'])))
                done = len(received) == len(payload)
                body = json.dumps({'sha256': digest}).encode() if done else b''
                self.send_response(201 if done else 204)
                self.send_header('Upload-Offset', str(len(received)))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'payload.bin'
            fixture.write_bytes(payload)
            with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    args = SimpleNamespace(http_base=f'http://127.0.0.1:{server.server_port}', http_ca_file=None)
                    result = transfer(args, {'task_id': 'test', 'ticket': 'test', 'sha256': digest}, fixture, 'upload')
                    self.assertTrue(result['sha256_ok'])
                    self.assertEqual(hashlib.sha256(received).hexdigest(), digest)
                finally:
                    server.shutdown()
                    worker.join()


if __name__ == '__main__':
    unittest.main()
