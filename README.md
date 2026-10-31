# 我的 Web 网盘攻防战（Thesis Drive）

电子科技大学「一年级新生课外创新实践项目计划」优秀作品，选题《我的 Web 网盘攻防战：白帽子与黑帽子的 PK》。这是一套以真实 Web 网盘为载体的攻防教学系统：完整业务控制面、独立文件数据面、安全网关、可控靶场与可观测性能实验，组成一条可复现的「攻击 → 告警/拦截 → 加固 → 对比」闭环。

- 团队：董庆锋、谭念周、罗利伟、王朝旭（计算机（网安）学院 · 网络空间安全专业 2025 级）
- 指导教师：李忻洋（实验师）

> 默认是安全模式。漏洞开关只有在 `LAB_MODE=true` 的隔离实验环境中才会生效；不要把 `course-unprotected` 或 `unprotected` profile 暴露到公网。

## 架构

```mermaid
flowchart LR
    B["Vue 网盘 / 攻防面板"] --> N["Nginx：TLS 与统一入口"]
    N --> G["security-gateway<br/>Java / Spring"]
    G --> C["drive-core<br/>Python CFMS 0.8"]
    N --> T["transfer-data-plane<br/>Java / WebFlux"]
    C --> D["MySQL：业务事务"]
    C <--> R["Redis：缓存、会话、可靠事件"]
    T <--> R
    C --> M["MinIO：对象元数据访问"]
    T --> M["MinIO：文件字节流"]
```

- `security-gateway`：WebSocket 公网边界、WAF、限流、关联审计、实验开关和管理鉴权。
- `drive-core`：认证、ACL、目录、版本、回收站、搜索和传输授权；`thesis` 支线已包含 CFMS 上游 `master@941404c`，后续定制均落在该支线。
- `transfer-data-plane`：8 MiB 有界分块、断点续传、HTTP Range、RS256 票据、MinIO 和 Redis Stream；不访问 Core 数据库。

Java 的拆分依据是安全边界和负载特征，而不是“为了换语言”：公网安全策略与大文件 I/O 可以独立扩缩、限流和故障处理；身份、目录、ACL 等强事务模块仍留在 Python 模块化单体中。

## 攻防教学靶场

- 双层漏洞设计：五类业务漏洞模拟加上 SSRF/JNDI 等扩展实验点，全部由 `LAB_MODE`、管理权限、实验数据与蜜饵对象共同界定隔离范围；实验点支持运行时热插拔，关闭后网盘仍按原有授权路径运行。
- 攻击链编排：认证绕过、命令执行、路径穿越提权、排序注入四条攻击链在组内演练中完整复现。前一步的证据是后一步的前置条件，过程依赖写入服务端状态，演示可重复、结果可追溯，走完可复位。
- 安全事件面板：WAF 拦截、蜜饵访问与关联审计统一在网关记录，实验结论可回溯到具体用户、资源、请求回执与安全事件。

## 性能实测（真机）

结题评测在一台 104 核 Linux 服务器上完成，走完整 HTTPS 入口（客户端 → Nginx → 安全网关 → Core / Transfer），8 MiB 分块上传/下载的聚合吞吐（MiB/s，成功文件口径）：

| 方向 | 对象大小 | 1 并发 | 8 并发 | 32 并发 | 64 并发 |
| --- | --- | ---: | ---: | ---: | ---: |
| 上传 | 1 MiB | 15.7 | 75.0 | 167.0 | 227.3 |
| 上传 | 8 MiB | 24.9 | 184.4 | **428.1** | 105.0 |
| 上传 | 64 MiB | 29.5 | 50.4 | 54.4 | 52.7 |
| 下载 | 1 MiB | 57.5 | 322.0 | 482.3 | 480.9 |
| 下载 | 8 MiB | 206.6 | 831.5 | **862.6** | 789.6 |
| 下载 | 64 MiB | 144.8 | 826.3 | **1099.0** | 873.1 |

- 安全网关开销（并发 1，与直连 Core 对照）：服务信息、目录列举、全文检索三类操作吞吐分别下降约 9.4%、8.5%、11.7%。
- 完整入口共 45 个上传 + 45 个下载文件：上传全部通过服务端摘要核对并获得 Core 业务确认，下载全部通过客户端 SHA-256 核对。
- 8 MiB 上传在 32 并发时相对单流约 17 倍、接近线性扩展；并发继续升高后受对象存储往返时延与全文件摘要写入约束而回落。
- 以上为短时、多轮工程测量，只陈述已测场景，不外推为生产级容量结论。

## 一键启动（Linux / Docker Compose）

要求 Docker Engine 与 Docker Compose v2。根目录执行：

```bash
cp .env.example .env
# 先替换 .env 中全部 change-this-* 开发口令，再启动服务
docker compose --env-file .env --env-file profiles/hardened.env up --build -d
docker compose ps
```

打开 `https://localhost`。开发证书是镜像构建时生成的自签证书，首次访问需由浏览器确认。Grafana 位于 `https://localhost/grafana/`。默认只监听 `127.0.0.1`；内网靶场请按 [攻防阶段内网部署手册](LAN_DEPLOYMENT.md) 显式选择网卡、生成口令和证书 SAN。

开发证书默认只覆盖本机入口。内网脚本可为指定 IP/DNS 增加 SAN；正式环境仍应使用匹配域名的受信任证书。

首次管理员密码：

```bash
docker compose exec drive-core cat /app/state/admin_password.txt
```

WAF/漏洞管理面板需要 `.env` 中的 `CARAPACE_ADMIN_TOKEN`，令牌只保存在浏览器 `sessionStorage`。

切换实验 profile 后重建网关：

```bash
docker compose --env-file .env --env-file profiles/baseline.env up -d --force-recreate drive-core security-gateway
```

可选 profile：

- `hardened`：漏洞关闭，WAF 全开（默认答辩入口）。
- `baseline`：隔离漏洞模拟保持开启，WAF 全开（用于采集拦截证据）。
- `course-unprotected`：九项课程任务所需的隔离模拟开启、WAF 关闭，扩展高危端点保持关闭。
- `unprotected`：包括 SSRF/JNDI 等扩展实验在内的全部漏洞开启、WAF 关闭，仅用于另行授权的隔离专项靶场。

停止服务保留数据用 `docker compose down`；只有明确要清空实验数据时才使用 `docker compose down -v`。

## 本地验证

```powershell
./scripts/verify.ps1
```

或分别执行：

```powershell
# drive-core
Set-Location cfms_on_websocket-master
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe -e '.[cluster,mysql,ext_oidc_sso]' --group dev
.venv/Scripts/python.exe -m pytest -q

# security-gateway / transfer-data-plane
../carapace/gradlew.bat test bootJar
../transfer-data-plane/gradlew.bat test bootJar

# frontend
Set-Location ../thesis_frontend
npm ci
npm test
npm run build
```

当前实现证据和待完成实验见 [EVIDENCE.md](EVIDENCE.md)，详细设计见 [MICROSERVICE_ARCHITECTURE.md](MICROSERVICE_ARCHITECTURE.md)。2026-09-08 已融合 CFMS 0.8.0 / 协议26，并补测本地与服务器裸服务、集成控制面及完整HTTPS文件路径；原始数据、失败记录和汇总见 [本次测评记录](benchmarks/records/2026-09-08/summary.json) 与 [运行说明](benchmarks/README.md)。现网保留上传消费修复，新版本在独立实例验证；现网旧库升级需另做MySQL迁移演练。

## 安全设计要点

- 传输票据为 RS256，绑定 `task_id、username、operation、object_key、max_size、jti、exp`，Core 只分发短期票据，Transfer 只持公钥。
- 上传完成使用 Redis Stream 消费者组；Core 数据库事务成功后才 ACK，重复事件必须幂等。
- 文件链路应表述为 HTTPS/WSS 传输加密与 SHA-256 完整性保护，不宣称端到端加密。
- MySQL、Redis、MinIO、Core 均无宿主端口，仅 Nginx 暴露 `80/443`。
