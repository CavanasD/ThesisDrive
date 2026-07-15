# Transfer Data Plane

Java 21 + Spring Boot WebFlux 的独立文件传输数据面。业务权限、目录与配额仍由 Drive Core 决定；本服务只校验 Core 签发的短期 RS256 ticket，执行有界内存的对象上传和 Range 下载。

## 协议

Core 先创建 Redis hash `transfer:session:{task_id}`，再签发 JWT。Redis 与 JWT 共同绑定：

- `task_id`
- `username`
- `operation`: `upload` 或 `download`
- `object_key`
- `max_size`: 本次对象的精确字节数
- Redis 与 JWT 均可带 `expected_sha256`；Redis 另有 `offset`、`status`、`created_at`、`expires_at`
- JWT 另有 `sub`、`iss`、`aud`、`iat`、`exp` 和随机、非 `task_id` 的 `jti`

若客户端在准备阶段提供完整文件校验值，Core 会同时绑定到 Redis session 和 ticket；否则 Transfer 在最终落盘时计算 SHA-256 并通过可靠事件交给 Core。`task_id` 绑定 URL/session，随机 `jti` 只标识本次短期票据。一个短票据在过期前会被同一任务的多个 8 MiB PUT 或 HTTP Range 复用，因此 `jti` 不做单次消费。

服务只配置 RSA 公钥，不持有 Core 私钥。默认开发公钥只能让应用启动；联调时必须用 `TRANSFER_PUBLIC_KEY_LOCATION` 指向 Core 私钥对应的公钥。

### 上传

```http
PUT /api/v1/transfers/{task_id}
Authorization: Bearer <ticket>
Content-Type: application/octet-stream
Content-Range: bytes 0-8388607/16777216
Content-Length: 8388608
X-Chunk-SHA256: <optional chunk digest>
```

- 每块最多 8 MiB，按 `offset` 严格顺序写入。
- `HEAD /api/v1/transfers/{task_id}` 返回权威的 `Upload-Offset`、`Upload-Length` 与 `Upload-Status`。
- 完全落在当前 offset 之前的重复块视为幂等重试，返回 `204` 和当前 `Upload-Offset`，不会重复写入。
- offset 有间隙或部分重叠返回 `409 offset_conflict`。
- 非最终块返回 `204`；完成后返回 `201` 和 `{task_id, object_key, size, sha256, status}`。
- 0 字节对象使用 `Content-Range: bytes */0` 和空 body。

网络 DataBuffer 逐个写入临时文件，不聚合整个块或整个文件。最终块到达后，服务流式计算全文件 SHA-256、校验大小，再从临时文件流式 `putObject` 到 MinIO。内存上界由网络/文件缓冲区决定，不随文件大小增长。

### 下载

```http
GET /api/v1/transfers/{task_id}/content
Authorization: Bearer <ticket>
Range: bytes=1048576-2097151
```

返回 `200` 或 `206`，并带 `Accept-Ranges`、`Content-Length`、`Content-Range` 和 `ETag`。只支持单一 byte range，支持 `start-end`、`start-` 和 `-suffixLength`。完整或 Range 响应流成功结束后才把会话标为 `completed`；读取异常或客户端取消保留可重试状态。

为支持浏览器原生 `<a>` 流式保存，下载端点也接受 GET-only 的 `?ticket=<JWT>`。响应带 `Cache-Control: no-store` 与 `Referrer-Policy: no-referrer`；生产日志和反向代理必须屏蔽该查询参数。

### 完成事件

成功上传会向 Redis Stream `transfer:completed` 写入：

`event_id`, `task_id`, `object_key`, `size`, `sha256`, `status`, `completed_at`

Core 消费者应以 `event_id`/`task_id` 做幂等确认。Redis Stream 默认保留约 10,000 条记录。

数据面写入对象并发布事件后返回的 `201` 只代表字节落盘。浏览器必须继续通过 Core 的 `get_transfer_status` 等待 MySQL 事务完成；Core 返回 `failed`（例如并发配额二次检查失败）时不得提示上传成功。失败事件若带 `orphaned=true`，Core 会在 ACK 前继续删除对象。

## 运行

需要 Java 21、Redis 和 S3 兼容的 MinIO。配置环境变量后：

```powershell
.\gradlew.bat test
.\gradlew.bat bootRun
```

或构建容器：

```powershell
docker build -t thesis-transfer-data-plane .
docker run --rm -p 8082:8082 -v thesis-transfer-data:/var/lib/transfer-data-plane/uploads thesis-transfer-data-plane
```

Dockerfile 不声明匿名 volume；生产或 Compose 应显式把持久卷挂载到 `/var/lib/transfer-data-plane/uploads`。运行镜像内安装了 `curl`，Docker healthcheck 会探测 `/actuator/health`。

关键环境变量：

| 变量 | 默认值 |
|---|---|
| `TRANSFER_PORT` | `8082` |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | `localhost`, `6379`, 空 |
| `MINIO_ENDPOINT` | `http://localhost:9000` |
| `MINIO_BUCKET` | `thesis-drive` |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | `minioadmin`, `minioadmin`（仅开发） |
| `TRANSFER_PUBLIC_KEY_LOCATION` | `classpath:keys/dev-transfer-public.pem` |
| `TRANSFER_JWT_ISSUER` | `thesis-drive-core` |
| `TRANSFER_JWT_AUDIENCE` | `transfer-data-plane` |
| `TRANSFER_TEMP_DIRECTORY` | `./data/uploads`（容器内自动改为持久卷路径） |
| `TRANSFER_ALLOWED_ORIGINS` | 本地 Vite/Nginx 地址 |

Redis session 和本地未完成文件的保留期均为 24 小时。本地清理任务每小时执行；Redis 自身 TTL 清理 session。单实例使用本地持久卷即可，多副本部署必须给所有副本提供同一个共享临时卷，或后续改成 MinIO multipart session。

## 运维端点

- `/actuator/health`（含 Redis 健康信息）
- `/actuator/prometheus`
- 自定义指标 `transfer.upload.bytes`、`transfer.upload.completed`、`transfer.download.bytes`

## 测试

JUnit 覆盖：

- RS256 正确/错误签名与 ticket claims
- 完整、开放、suffix、非法 HTTP Range
- 已提交上传块重试不重复落盘
