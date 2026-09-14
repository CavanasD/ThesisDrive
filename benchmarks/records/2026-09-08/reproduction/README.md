# ThesisDrive HTTP 数据面压测

这个目录提供只依赖 Python 标准库的可复现实验工具，针对 `transfer-data-plane` 的原始字节接口测试：

- `PUT /api/v1/transfers/{task_id}`：8 MiB 以内的 `Content-Range` 分块上传；
- `GET /api/v1/transfers/{task_id}/content`：8 MiB 以内的 HTTP `Range` 分段下载；
- Bearer 票据认证、幂等上传、SHA-256 完整性校验；
- 并发 `1/10/20/50`、默认重复 3 次、按秒预热；
- JSON 原始结果与 CSV 汇总结果；
- 吞吐、TTFB、完成时间 p50/p95/p99、错误率。

工具不会对文件调用 `read()` 无参数版本。上传每个 worker 最多持有一个配置大小的块（默认及上限均为 8 MiB）；下载响应以 64 KiB 递增读取。因此 1 GiB 文件不会整体进入内存。并发总内存约为 `并发数 × 分块上限` 加上 Python/网络缓冲开销。

## 1. 准备测试文件

测试文件应提前生成并在整个实验中保持不变。下面示例以小块循环写出 100 MiB 文件：

```powershell
New-Item -ItemType Directory -Force benchmarks\fixtures | Out-Null
@'
from pathlib import Path
p = Path("benchmarks/fixtures/100MiB.bin")
block = bytes(1024 * 1024)
with p.open("wb") as f:
    for _ in range(100):
        f.write(block)
print(p)
'@ | python -
python -c "import hashlib; print(hashlib.file_digest(open('benchmarks/fixtures/100MiB.bin','rb'), 'sha256').hexdigest())"
```

论文实验建议分别准备 1 MiB、100 MiB 和 1 GiB 文件，并在结果旁记录 CPU、内存、磁盘、Docker 版本和网络条件。

## 2. 准备 sessions JSON

复制 `example.sessions.json`，用 Core 的 `prepare_upload` / `prepare_download` 结果替换 URL 与短期票据。路径相对于 sessions JSON 所在目录解析。

单项格式：

```json
{
  "name": "upload-worker-01",
  "operation": "upload",
  "upload_url": "http://localhost:8082/api/v1/transfers/task-id",
  "ticket": "short-lived-rs256-ticket",
  "file": "fixtures/100MiB.bin",
  "sha256": "expected-lowercase-sha256"
}
```

下载将 `operation` 改为 `download`，并提供 `download_url`；可以额外提供 `size`。也可以在一项中同时提供 `upload_url` 和 `download_url`，省略 `operation`，并分别使用 `upload_ticket`、`download_ticket`。

注意：上传票据绑定单个任务。做并发 N 时，应准备至少 N 个独立上传 session；否则工具会轮询复用已有 session，只适合验证幂等路径，不能代表真实新增对象吞吐。重复轮次之间也应通过实验复位重新签发任务，或确认服务端允许同一对象按幂等语义重放。下载 session 可以安全复用。

报告绝不会写入票据或请求 URL。

## 3. 运行

完整矩阵：

```powershell
python benchmarks\drive_benchmark.py `
  --sessions benchmarks\sessions.local.json `
  --operations both `
  --concurrency 1,10,20,50 `
  --repeats 3 `
  --warmup-seconds 15 `
  --chunk-size 8388608
```

只跑下载并把报告写到指定位置：

```powershell
python benchmarks\drive_benchmark.py `
  --sessions benchmarks\sessions.local.json `
  --operations download `
  --concurrency 1,10,20,50 `
  --repeats 3 `
  --warmup-seconds 15 `
  --output-prefix benchmarks\results\http-download
```

默认报告位于 `benchmarks/results/drive-benchmark-时间戳.json|csv`。预热以“完整批次”为中断边界：已经开始的大文件传输会完成，因此实际预热时间可能略高于指定秒数。

自签发 CA 使用 `--ca-file path/to/ca.pem`。工具没有跳过 TLS 校验的开关，避免答辩实验误用不安全配置。

## 4. 指标口径

- `throughput_mib_s`：成功传输的总字节数 / 各重复批次墙钟时间之和；可正确反映并发吞吐。
- `ttfb_*_ms`：每个逻辑文件第一次 HTTP 响应头到达的时间分布。
- `completion_*_ms`：每个逻辑文件从首个请求开始到完整 SHA-256 校验结束的时间分布。
- `error_rate`：失败逻辑文件数 / 总尝试数；SHA-256、Range、offset 或 HTTP 校验失败均计入错误。

JSON 还保留每轮墙钟时间和每个逻辑文件的结果，但不会保存密钥、票据或 URL。

## 5. 测试

测试会启动本地假 HTTP 服务，真实验证上传分块、下载 Range、Bearer 认证、SHA-256 与汇总输出：

```powershell
uv run --project cfms_on_websocket-master --locked python -m unittest discover -s benchmarks\tests -v
```

## 6. Core 控制面与目录检索基线

CFMS 0.8 自带压测器用于裸服务。必须使用独立 linked worktree；`--managed-reset` 会重置其中的测试数据库和文件。2026-09-08 的裸服务版本为上游 `a004142`，不加载项目扩展。

```powershell
git -C cfms_on_websocket-master worktree add --detach ../tmp/cfms-benchmark-upstream a004142
Set-Location tmp/cfms-benchmark-upstream
uv run --locked python -m tests.stress.ws_load --scenario auth-read --users 4 --duration 5s --managed-reset --output ../native-read.json
```

完整裸服务矩阵由 `benchmarks/bare_matrix.py` 编排：本地和服务器各54轮，覆盖并发1/4/10，服务信息、认证混合读取及1/8 MiB原生上传下载，每组3次、每次5秒。

`benchmarks/system_evaluation.py` 用于独立部署的集成实例，支持 `--mode controls` 和 `--mode transfers`。控制实验自动创建250条目录语料，并验证检索首屏128条；文件实验自动创建独立任务、校验SHA-256，并等待上传的Core业务确认。密码通过 `--password-file` 从服务器文件读取，JSON不保存凭据。HTTPS分别通过 `--ca-file` 和 `--http-ca-file` 校验证书。

本次原始记录与汇总位于 `benchmarks/records/2026-09-08/`：`local-bare`、`server-bare`、`server-system`、`summary.json`及3份CSV。运行 `python benchmarks/summarize_evaluation.py` 可重新汇总。原生工具的原始 `throughput_rps` 包括失败响应；汇总脚本另按成功数/墙钟时间计算成功吞吐。原生文件场景包含业务准备和清理，载荷也不同，不能与HTTP纯数据阶段直接计算加速倍数。

正式集成控制面使用异步WebSocket客户端；早期同步TLS客户端的握手失败、分块204响应解析问题及下载状态回执观察保留在 `server-system/preliminary`，不混入修正后的正式样本。100 MiB/1 GiB、长时间稳态和公网客户端矩阵尚未执行。

## 7. 裸服务连接数与准入策略补测

`bare_extended.py` 包装上游压测器，保留每次响应的状态码、拒绝 scope 和成功时延；不改服务端源码。仅在一次性 linked worktree 中使用 `--managed-reset`。

- 默认组保留连接上限64、单IP连接上限16、全局在途请求上限12，测10/16连接。
- `BARE_POLICY=expanded` 仅将上述三个准入上限改为128，测10/32/64连接；单连接在途上限仍为8。认证在正式计时前最多2个并行完成。
- 服务信息与认证后随机目录/用户/组读取，每组3轮、每轮20秒，无思考时间的闭环请求，每连接同时发出1个请求。
- 另以总速率50请求/秒对照默认10连接与扩大准入64连接，区分连接数量和到达速率。
- 默认16连接认证准备被503拒绝的运行单独保存为 `*.setup-failure.json` 和日志，不计为已登录读取的零吞吐样本。首个同类失败的原日志也保留。

服务器编排脚本 `bare_extended_matrix.py` 使用现有一次性 `/bench/worktree` 与 `/bench/extended`，与现网、集成测试实例的数据库和文件完全分开。样本存于 `records/2026-09-08/server-bare-extended/`；运行 `summarize_bare_extended.py` 按测量阶段汇总成功吞吐和合并p95/p99，并断言响应计数与上游阶段统计一致。客户端和服务端共享2 CPU/1 GiB容器，本测量不是独占硬件的最大容量认证。

`bare_trace_server.py` 是另行运行的观察用引导程序，记录终结帧写出到请求名额释放之间的重叠；设置 `BARE_TRACE_OUT` 时由包装器启用。其 `trace-*.json` 不进入正式吞吐汇总，也未部署到现网。原始5秒图归档在补测目录的 `original-5s-figure/`。
