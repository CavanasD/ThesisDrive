import asyncio, json, secrets, ssl, struct, time
from websockets.asyncio.client import connect

async def go(url, origin, label):
    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    ws = await connect(url, ssl=ctx, proxy=None, origin=origin, open_timeout=30)
    async def ask(id_, action, data, auth=None):
        env = {"action": action, "data": data}
        if auth: env.update(auth); env["nonce"]=secrets.token_hex(16); env["timestamp"]=time.time()
        await ws.send(struct.pack(">IB", id_, 0) + json.dumps(env).encode())
        while True:
            f = await asyncio.wait_for(ws.recv(), 30)
            if struct.unpack(">I", f[:4])[0]==id_ and f[4]==1:
                return json.loads(f[5:])
    print(f"\n########## {label} ##########")
    # classic SQLi / path traversal / cmd injection payloads that WAF rules would catch
    tests = [
        ("sqli quote-or", "lab_sqli", {"query": "' OR '1'='1", "dataset": "LAB_USERS"}),
        ("path traversal", "lab_path_traversal", {"path": "../../etc/passwd"}),
        ("cmd inj semicolon", "lab_rce", {"command": "id; cat /etc/passwd"}),
        ("cmd inj pipe", "lab_rce", {"command": "id | md5sum"}),
        ("cmd inj backtick", "lab_rce", {"command": "echo `id`"}),
        ("cmd inj $()", "lab_rce", {"command": "echo $(id)"}),
        ("cmd inj &&", "lab_rce", {"command": "id && hostname"}),
    ]
    for name, action, data in tests:
        r = await ask(1, action, data)
        d = r.get("data", {})
        blocked = r.get("waf") is True or r.get("code") == 403
        print(f"  {name:20s} code={r.get('code'):<4} waf={r.get('waf')} blocked={blocked} msg={r.get('message')[:52]}")
    await ws.close()

async def main():
    await go("wss://127.0.0.1:8008/ws", "https://LAB_HOST:8008", "THROUGH NGINX :8008 -> security-gateway -> WAF")

asyncio.run(main())
