# 报告声明 → 自动化证据

最后更新：2026-07-15。

| 声明 | 自动化证据 | 当前结果 |
|---|---|---|
| 固定最新 CFMS 0.4 基线 | 子模块祖先 `6b2f2d3a`；Core 全量 pytest；Ruff | `351 passed`；Ruff 通过 |
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
| 性能验收门槛 | 固定硬件执行 benchmark matrix | 待实测，禁止填造数据 |

## 已知验证边界

- 当前 Windows 开发机没有 Docker CLI，因此镜像构建和完整 Compose E2E 必须在 CI 或目标 Linux 主机完成。
- 本机没有独立 Redis 服务，Redis Lua 已由参数/脚本契约测试和 Java 编译覆盖；真实 Redis、重启恢复与未 ACK 重放仍由 Compose CI/目标机验证。
- Core 的 TLS 私钥仅挂载到 Core；Gateway 仅挂载单独的只读证书卷，并使用 `CFMS_TLS_CA_CERT` 保留标准主机名校验。证书 SAN 与卷隔离由 CI 验证。
- MinIO、Redis 重启和 Transfer/Core 停机场景已有架构与健康检查，仍需在 Compose 实例上执行故障注入并保存 Grafana 截图。
- 传输票据默认有效 900 秒；低速超大文件若中途过期，可通过“重试/续传”重新签票并从服务端 offset 继续，尚未做无感自动刷新。
- IndexedDB 保留会话和 offset，但浏览器刷新后仍需用户重新选择同一原文件；跨页面恢复的文件重关联体验尚未闭环。
- 原生 `<a>` 下载不会向页面暴露真实写盘完成回调，因此前端只能表示“已开始下载”；服务端会在响应流成功结束后记录可信终态。
- SQLite 并发回归已覆盖重名竞争；父目录 `SELECT ... FOR UPDATE` 的跨进程保证仍需在真实 MySQL Compose 环境专项验证。
- Nginx 自签证书只面向 `localhost/127.0.0.1` 开发入口；部署真实域名或主机 IP 前必须替换证书。
- `unprotected` 仅用于隔离实验；所有默认配置保持漏洞关闭。
