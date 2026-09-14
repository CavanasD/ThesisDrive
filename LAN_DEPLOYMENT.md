# 攻防阶段内网部署手册

这套部署把公开入口固定到一张明确的 IPv4 网卡，自动生成本地强口令，并让 Nginx 自签证书包含内网 IP/DNS SAN。默认仍只监听 `127.0.0.1`，不会因为误用实验 profile 就自动暴露到所有网卡。

## 1. 网络选择

- `course-unprotected` 只能放在 VMware host-only、隔离 VLAN 或仅允许课程测试机访问的网段。
- `baseline` 仍保留教学漏洞模拟，只是由 WAF 拦截，也应限制在授权网段。
- `hardened` 用于首次冒烟、最终复测和答辩入口。
- 不要把 `BIND_ADDRESS` 写成 `0.0.0.0`。部署脚本会拒绝通配地址。

当前 Windows 开发机常见的安全选择是 VMware `VMnet1` 的 host-only 地址；具体模式仍应在 VMware 虚拟网络编辑器中确认。校园 WLAN、可路由公网地址或 Tailscale 地址不应直接运行 `course-unprotected`。

## 2. 前置条件

- Docker Engine / Docker Desktop 与 Docker Compose v2。
- 建议至少 8 GiB 可用内存和 20 GiB 可用磁盘。
- 一张已确定的内网 IPv4 地址，例如 `192.168.56.101`。
- 防火墙只允许授权测试网段访问 TCP 443；TCP 80 仅用于 HTTPS 跳转，可不对外开放。

## 3. 生成部署环境

在仓库根目录运行：

```powershell
pwsh ./scripts/prepare-lan-env.ps1 -BindAddress 192.168.56.101
```

如果测试者使用 DNS 名称访问：

```powershell
pwsh ./scripts/prepare-lan-env.ps1 -BindAddress 192.168.56.101 -PublicHost drive-lab.internal
```

脚本生成 `.env`，其中包含随机数据库口令、Redis 口令、MinIO 口令、WAF 管理令牌和 Grafana 管理口令。它不会把口令打印到终端。`.env` 不得提交到仓库或发到报告中。

## 4. 启动与切换

先以安全模式完成部署冒烟：

```powershell
pwsh ./scripts/deploy-lan.ps1 -Profile hardened
```

部署脚本会验证 Compose 配置、构建并等待全部服务健康、检查 HTTPS 首页，并把仅含公钥的客户端信任证书导出到系统临时目录。

准备好两个课程账号、两份无敏感信息的测试文件并做快照后，按实验阶段切换：

```powershell
# 九项任务所需的隔离模拟开启、WAF 关闭：只在隔离网段复现
pwsh ./scripts/deploy-lan.ps1 -Profile course-unprotected -NoBuild

# 同一批输入由 WAF 拦截，采集告警证据
pwsh ./scripts/deploy-lan.ps1 -Profile baseline -NoBuild

# Core 关闭实验入口，WAF 保持开启，完成修复后复测
pwsh ./scripts/deploy-lan.ps1 -Profile hardened -NoBuild
```

`baseline` 和 `course-unprotected` 若绑定到非 RFC1918 地址会被脚本拒绝。只有已经配置外部网络 ACL、明确确认仍属于授权靶场时，才能显式增加 `-AllowNonPrivateLabAddress`。

仓库原有的 `unprotected` 还会启用 SSRF、JWT `alg=none`、反射 CORS 和 JNDI lookup 等扩展实验，不属于本轮九项任务。部署脚本默认拒绝它；专项实验必须在单独授权和隔离条件下显式增加 `-AllowExtendedVulnerabilities`。

Linux 主机可使用同一 `.env` 和 profile 直接运行：

```bash
docker compose --env-file .env --env-file profiles/hardened.env up --build -d --wait
```

切换 profile 时必须同时更新 `drive-core` 与 `security-gateway`；直接再次运行完整的 `docker compose up -d --wait` 即可由 Compose 检测环境变化并重建相关服务。

## 5. 客户端与防火墙

测试者访问 `https://<内网地址>/`，Grafana 位于 `/grafana/`。自签证书已经包含所配置的 IP 或 DNS 名，但客户端仍需导入部署脚本导出的 `.crt` 公钥证书，或在课程环境中手工确认浏览器警告。

Windows 防火墙示例（管理员 PowerShell，按实际网段替换）：

```powershell
New-NetFirewallRule -DisplayName 'Thesis Drive Lab HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress 192.168.56.101 -LocalPort 443 -RemoteAddress 192.168.56.0/24
```

部署脚本不会自动修改防火墙，避免意外扩大授权范围。

## 6. 九项任务与当前系统的对应关系

| 任务 | 当前测试入口与预期 |
|---|---|
| 弱口令/爆破 | 使用真实账号流程做不超过 10 次低速测试。控制面是 WebSocket 协议，不是普通 `/login` 表单，不能直接照抄文档中的 Hydra HTTP 命令。 |
| SQL 注入 | 使用隔离的 `lab_sqli` 固定数据集；`course-unprotected` 观察模拟结果，`baseline` 观察 WAF 拦截，`hardened` 应无实验能力。 |
| XSS | Vue 默认文本转义与 Gateway XSS WAF 是主要验证点；当前没有故意提供真实存储型 XSS，不要为“完成任务”引入可执行脚本。 |
| CSRF | 控制面使用显式令牌而非浏览器 Cookie，数据面使用短期 Bearer ticket，传统 Cookie CSRF 条件不成立；报告中做架构审计并记录“不适用”的证据。 |
| 越权/路径穿越 | 使用 `lab_idor`、`lab_path_traversal` 的隔离对象和虚拟文件系统，不读取真实文件或其他用户数据。 |
| 文件上传 | 数据面校验危险扩展名、声明类型和 PE/ELF 魔数，文件进入 MinIO/非 Web 根目录；只上传无害标记样本，不使用真实 WebShell。 |
| SSTI | 前端是静态 Vue SPA，没有把用户输入作为服务端模板二次渲染；以代码审计和无害 `{{7*7}}` 原样显示为证据。 |
| 命令执行 | `lab_rce` 只返回固定 allowlist 结果，不创建 shell 或子进程；仅使用课程固定命令。 |
| 会话/Cookie | 重点验证登录令牌、退出和旧令牌失效；系统没有传统会话 Cookie 时，不虚构 Cookie 属性测试结果。 |

额外的 SSRF、JWT `alg=none`、CORS、Log4Shell 模拟不属于这九项必做任务，除非教师另行要求，不需要扩大测试范围。

## 7. 每轮证据清单

每个用例固定保存：profile 名称、时间、测试账号、正常请求、只改一个参数后的请求、状态码/页面结果、Gateway/WAF 日志、Core 日志，以及相同输入在下一 profile 下的复测结果。不得把完整 Cookie、Token、管理令牌或真实密码放进截图和报告。

查看服务与日志：

```powershell
docker compose --env-file .env --env-file profiles/baseline.env ps
docker compose --env-file .env --env-file profiles/baseline.env logs --since 10m nginx security-gateway drive-core transfer-data-plane
```

停止并保留数据：

```powershell
docker compose --env-file .env --env-file profiles/hardened.env down
```

不要使用 `down -v`，除非已经备份且明确要清空全部实验数据。
