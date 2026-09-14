# 报告声明 → 自动化证据

最后更新：2026-08-29。

| 声明 | 自动化证据 | 当前结果 |
|---|---|---|
| CFMS 主线基线 | `thesis` 已包含 `cfms-dev/upstream/master@941404c` | 已同步 |
| 协议 15 奇数流 ID 与 FIFO | `cfmsClient.test.js` | 通过 |
| HTTP 分块、暂停/续传与 IndexedDB | `transferClient.test.js`：断网后 `prepare + HEAD` 恢复 offset | 通过 |
| 数据面完成不冒充业务完成 | Core 同时核对 `FileTask`；Vue 轮询 `get_transfer_status` | 通过 |
| RS256 票据绑定与可靠事件幂等 | Core `test_transfer_data_plane.py`；Transfer contract JUnit | 通过 |
| 配额拒绝和失败回滚无已知 MinIO 孤儿 | Core 重放测试：删除失败不 ACK，恢复后继续删除 | 通过 |
| 上传类型策略使用权威文档元数据 | 客户端伪报 filename/MIME 回归测试 | 通过 |
| 同目录重名并发只有一个赢家 | `test_documents.py -k concurrent` | `2 passed` |
| Gateway 上下文可启动 | Gateway 全量 JUnit + `bootJar` | `16 passed` |
| 管理鉴权与 LAB_MODE 双门禁 | Carapace Security/Vuln JUnit | 通过 |
| Gateway 指标鉴权 | Prometheus `http_headers` 从只读 token 文件发送 `X-Admin-Token`；CI `promtool check config` | 待 CI/Linux 主机验证 |
| WAF 有界批量持久化 | `WafEventPersisterTest` + Prometheus 指标 | 通过 |
| Transfer Range、票据篡改、分块重试、下载终态 | Transfer JUnit + `bootJar` | `28 passed` |
| 前端控制面、分享、传输与生产构建 | Vitest；`npm run build` | `25 passed`；构建通过 |
| 压测器分块、Range、SHA-256 与汇总 | Python unittest | `4 passed` |
| 浏览器基础冒烟 | 登录页与匿名 `?share=` 页面；控制台错误检查 | 通过 |
| 数据库迁移 | 单 Alembic head；旧 head 增量升级/降级；fresh schema DDL 编译 | 通过 |
| Compose 配置语法 | CI `docker compose config` | 本机无 Docker，待 CI/Linux 主机验证 |
| CFMS 控制面 / 检索基线 | 1/10/20 并发 × 10 秒，含 250 条目录检索语料 | [原始记录](benchmarks/records/2026-08-29-cfms-control-plane.json)，全组 0 错误 |
| HTTP 文件传输验收 | 固定硬件执行 upload/download benchmark matrix | 待 Docker/CI 数据面环境实测，禁止填造数据 |

## 已知验证边界

- 当前 Windows 开发机没有 Docker CLI，因此镜像构建和完整 Compose E2E 必须在 CI 或目标 Linux 主机完成。
- 本机没有独立 Redis 服务，Redis Lua 已由参数/脚本契约测试和 Java 编译覆盖；真实 Redis、重启恢复与未 ACK 重放仍由 Compose CI/目标机验证。
- Core 的 TLS 私钥仅挂载到 Core；Gateway 仅挂载单独的只读证书卷，并使用 `CFMS_TLS_CA_CERT` 保留标准主机名校验。证书 SAN 与卷隔离由 CI 验证。
- MinIO、Redis 重启和 Transfer/Core 停机场景已有架构与健康检查，仍需在 Compose 实例上执行故障注入并保存 Grafana 截图。
- 传输票据默认有效 900 秒；低速超大文件若中途过期，可通过“重试/续传”重新签票并从服务端 offset 继续，尚未做无感自动刷新。
- IndexedDB 保留会话和 offset，但浏览器刷新后仍需用户重新选择同一原文件；跨页面恢复的文件重关联体验尚未闭环。
- 原生 `<a>` 下载不会向页面暴露真实写盘完成回调，因此前端只能表示“已开始下载”；服务端会在响应流成功结束后记录可信终态。
- SQLite 并发回归已覆盖重名竞争；父目录 `SELECT ... FOR UPDATE` 的跨进程保证仍需在真实 MySQL Compose 环境专项验证。
- Nginx 自签证书默认只面向 `localhost/127.0.0.1`；内网部署脚本会为指定 IP/DNS 增加 SAN，正式环境仍需替换为受信任证书。
- `course-unprotected` 与 `unprotected` 仅用于隔离实验；所有默认配置保持漏洞关闭。

## 2026-08-29 实测性能（控制面与检索）

环境：Windows 11 Pro、Intel Core Ultra 9 275HX（24 逻辑处理器）、31.4 GiB 内存；每个用例使用全新隔离 SQLite/Core 进程，时长 10 秒、无速率上限。完整 JSON 含运行方式和每一项原始指标，见 [性能记录](benchmarks/records/2026-08-29-cfms-control-plane.json)。

| 场景 | 并发 | 吞吐（req/s） | p95（ms） | 成功率 |
|---|---:|---:|---:|---:|
| `server_info` | 1 / 10 / 20 | 271.143 / 268.301 / 262.365 | 4.479 / 43.064 / 80.755 | 100% |
| 已登录目录/用户/组读取 | 1 / 10 / 20 | 84.385 / 65.518 / 60.052 | 14.804 / 205.130 / 491.144 | 100% |
| 网盘控制面混合操作 | 1 / 10 / 20 | 96.237 / 75.424 / 72.976 | 19.944 / 299.016 / 575.082 | 100% |
| 目录检索（250 条语料） | 1 / 10 / 20 | 34.643 / 27.797 / 27.556 | 35.476 / 667.558 / 1168.377 | 100% |

以上是2026-08-29的历史控制面结果，不是HTTP文件传输结论。本次更新的服务器文件实验见下节。

## 2026-09-08 新版融合与服务器测评

- 上游 `dev` 已核对为 `a0041424e5b184f701fa7250c2f1535caa30afc7`，项目合并提交为 `ddcfd50`，另有本项目适配补丁。运行协议26、CFMS 0.8.0。
- 最新隔离回归：451 passed、2 skipped；前端30项通过并完成构建；HTTP中间分块204与最终201的压测器回归通过。
- 网关18项测试通过并完成构建。完整入口初测发现SQL规则误拦顶层认证令牌中的`--`；修复仅从WAF匹配文本中移除顶层token，Core仍验证原始凭据，data内注入仍接受检查；完整路径在修复后重测。
- 裸服务分别在Windows本地与Linux服务器执行54轮：并发1/4/10、每组3轮、每轮5秒，覆盖控制面与原生文件上传下载。高并发503及文件操作失败全部保留。
- 服务器完整HTTPS入口测试1/8/32 MiB文件、并发1/4、重复3轮；上传依据为摘要一致与Core业务确认，下载依据为客户端SHA-256一致。
- 原始JSON、3份CSV及环境、版本与源文件摘要见 [2026-09-08记录](benchmarks/records/2026-09-08/)。早期探针与失败记录单列preliminary；正式样本由异步WebSocket客户端生成。
- 上传消费者过滤Redis空消息批次，防止历史队列饿死新消息；新版redis-py显式使用10秒读取超时，超过5秒XREADGROUP阻塞窗口。现网空批次修复已落盘，新版完整系统使用独立thesis-eval实例，未执行现网整库版本升级。
- 现网网关已部署令牌误拦修复，并保留 `thesis-drive-security-gateway:rollback-20260908`。旧Core的MySQL任务时间FLOAT读回发生精度损失，造成新任务410；临时表复现后备份30条任务记录，仅扩宽start_time/end_time为DOUBLE并同步模型。随后经现网网关完成1 MiB上传、Core确认、下载SHA-256核对，探针夹具已清理。
- 最终检查：现网与隔离实例均运行，配置了健康检查的组件全部healthy；现网HTTPS首页200。裸服务压测容器已停止；新版Core和网关已固化为20260908-final隔离镜像。证据见日期目录内production与server-final-health记录。
- SQLite旧库副本升级至0460356a5ba6，用户、文档、文件、目录、分享行数保持一致；不据此声称MySQL现网迁移已验证。
- 下载初步探针中有字节与摘要正确而Redis会话仍为ready的观察。状态回执、100 MiB/1 GiB、长时间稳态、故障注入与教学效果仍需专项验证。
