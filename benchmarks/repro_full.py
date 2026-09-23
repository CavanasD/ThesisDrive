import argparse, asyncio, json, secrets, ssl, struct, time
from websockets.asyncio.client import connect

class C:
    def __init__(s, url, origin=None, ca=None):
        s.url, s.origin, s.ca = url, origin, ca
        s.frame = 1; s.auth = {}
    async def __aenter__(s):
        ctx = None
        if s.url.startswith("wss:"):
            ctx = ssl.create_default_context(cafile=s.ca)
            if not s.ca:
                ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        s.ws = await connect(s.url, ssl=ctx, proxy=None, origin=s.origin, open_timeout=30)
        return s
    async def __aexit__(s, *e): await s.ws.close()
    async def req(s, action, data=None, auth=True, raw=None):
        fid = s.frame; s.frame += 2
        if raw is not None: env = raw
        else:
            env = {"action": action, "data": data or {}}
            if auth and s.auth:
                env.update(s.auth); env["nonce"] = secrets.token_hex(16); env["timestamp"] = time.time()
        await s.ws.send(struct.pack(">IB", fid, 0) + json.dumps(env).encode())
        while True:
            f = await asyncio.wait_for(s.ws.recv(), timeout=30)
            if struct.unpack(">I", f[:4])[0] == fid and f[4] == 1:
                return json.loads(f[5:])
    async def login(s, u, p):
        r = await s.req("login", {"username": u, "password": p}, auth=False)
        if r.get("code") == 200: s.auth = {"username": u, "token": r["data"]["token"]}
        return r

def p(t, r):
    print(f"\n===== {t} =====\n" + json.dumps(r, ensure_ascii=False, indent=2)[:2200])
    return r

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws-url", default="wss://127.0.0.1:8008/ws")
    ap.add_argument("--origin", default="https://LAB_HOST:8008")
    ap.add_argument("--password", required=True)
    a = ap.parse_args()
    async with C(a.ws_url, a.origin) as c:
        p("login", await c.login("admin", a.password))
        p("sqli allowlisted", await c.req("lab_sqli", {"query": "' OR '1'='1", "dataset": "LAB_USERS"}))
        p("auth_bypass", await c.req("lab_auth_bypass", {"username": "lab-decoy-admin", "proof": "LAB-BYPASS-DEMO"}))
        p("idor", await c.req("lab_idor", {"object_id": "LAB-DOC-DECOY"}))
        p("path_traversal", await c.req("lab_path_traversal", {"path": "../decoys/honeytoken.txt"}))
        p("rce read-honeytoken", await c.req("lab_rce", {"command": "read-honeytoken"}))
        p("chain sandbox_breach traverse", await c.req("lab_chain_step", {"chain": "sandbox_breach", "step": "traverse"}))
        p("chain sandbox_breach execute", await c.req("lab_chain_step", {"chain": "sandbox_breach", "step": "execute"}))

asyncio.run(main())
