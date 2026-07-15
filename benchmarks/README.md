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
python -m unittest discover -s benchmarks\tests -v
```
