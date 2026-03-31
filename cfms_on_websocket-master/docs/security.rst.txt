安全特性
========

CFMS 实现了多层安全措施保护系统和数据。

.. contents:: 目录
   :local:
   :depth: 2

传输安全
--------

TLS/SSL 加密
^^^^^^^^^^^^

CFMS 使用 WSS（WebSocket Secure）协议，所有通信都经过 TLS/SSL 加密。

**自签名证书**

首次启动时，服务器自动生成自签名证书：

- 使用 ECC 算法（SECP256R1 曲线）
- 有效期 1 年（可配置）
- 存储在 ``content/ssl/`` 目录

**生产环境证书**

生产环境应使用受信任的证书：

.. code-block:: toml

   [server]
   ssl_keyfile = "/path/to/your/key.pem"
   ssl_certfile = "/path/to/your/cert.pem"

可以使用 Let's Encrypt 等免费 CA。

.. tip::

   对于内部部署或测试环境，可以使用 :doc:`certtools` 生成自定义的证书颁发机构和 SSL 证书。

证书验证
^^^^^^^^

客户端应验证服务器证书：

.. code-block:: python

   import ssl

   ssl_context = ssl.create_default_context()
   # 开发环境可以跳过验证
   # ssl_context.check_hostname = False
   # ssl_context.verify_mode = ssl.CERT_NONE

认证与授权
----------

密码安全
^^^^^^^^

**哈希算法**

- 使用 SHA-256 哈希
- 每个用户使用唯一的盐值（16 字节随机数）
- 密码存储格式：``hash(password + salt)``

**密码策略**

可配置的密码要求：

.. code-block:: toml

   [security]
   passwd_min_length = 8           # 最小长度
   passwd_max_length = 32          # 最大长度
   passwd_must_contain = [         # 必须包含
       "uppercase",
       "lowercase",
       "digit",
       "special"
   ]

**密码过期**

.. code-block:: toml

   [security]
   enable_passwd_force_expiration = true
   passwd_expire_after_days = 90

密码过期后强制用户修改。

**密码修改**

- 修改密码时重新生成盐值
- 重新生成用户专属 JWT 密钥
- 使所有现有令牌失效
- 记录修改时间

JWT 令牌
^^^^^^^^

**令牌生成**

.. code-block:: python

   import jwt
   import time

   payload = {
       "username": username,
       "exp": time.time() + 3600  # 1小时后过期
   }
   token = jwt.encode(payload, secret_key, algorithm="HS256")

**令牌验证**

.. code-block:: python

   try:
       payload = jwt.decode(token, secret_key, algorithms=["HS256"])
       username = payload["username"]
   except jwt.ExpiredSignatureError:
       # 令牌已过期
       pass
   except jwt.InvalidTokenError:
       # 令牌无效
       pass

**用户专属密钥**

每个用户有自己的 JWT 密钥（``User.secret_key``）：

- 密码修改时自动更换
- 使该用户的所有令牌失效
- 增强安全性

**令牌刷新**

令牌过期前可以刷新：

.. code-block:: json

   {
       "action": "refresh_token",
       "data": {},
       "username": "user",
       "token": "old_token"
   }

建议在令牌过期前主动刷新（如剩余 10 分钟时）。

访问控制
--------

多层权限检查
^^^^^^^^^^^^

1. **系统权限**：用户必须有对应的系统权限
2. **访问规则**：资源可定义访问规则
3. **访问授权**：可明确授予访问权限

详见 :doc:`access_control` 和 :doc:`groups_and_rights`。

最小权限原则
^^^^^^^^^^^^

默认情况下，用户只有最基本的权限。需要的权限必须明确授予。

审计日志
--------

操作记录
^^^^^^^^

所有敏感操作都会记录到审计日志：

.. code-block:: python

   from include.util.audit import log_audit

   log_audit(
       action="delete_document",
       result=200,
       target="doc123",
       username="admin",
       remote_address="192.168.1.100"
   )

日志内容
^^^^^^^^

- 操作类型（action）
- 操作用户（username）
- 操作结果（result，HTTP 状态码）
- 操作目标（target）
- 附加数据（data）
- 客户端 IP（remote_address）
- 时间戳（timestamp）

查看日志
^^^^^^^^

需要 ``view_audit_logs`` 权限：

.. code-block:: json

   {
       "action": "view_audit_logs",
       "data": {
           "limit": 100,
           "offset": 0
       },
       "username": "admin",
       "token": "token"
   }

日志分析
^^^^^^^^

定期分析审计日志：

- 失败的登录尝试
- 异常的访问模式
- 权限提升操作
- 数据删除操作

用户封禁
--------

封禁机制
^^^^^^^^

可以封禁用户的特定操作或完全封禁：

.. code-block:: json

   {
       "action": "block_user",
       "data": {
           "target_username": "user1",
           "reason": "违规操作",
           "end_time": 1704067200  # Unix时间戳，null表示永久
       },
       "username": "admin",
       "token": "token"
   }

封禁类型
^^^^^^^^

- **read**：禁止读取
- **write**：禁止写入
- **move**：禁止移动

封禁检查
^^^^^^^^

在执行操作前检查用户是否被封禁：

.. code-block:: python

   if user.is_blocked("read"):
       raise PermissionError("User is blocked from reading")

系统锁定
--------

Lockdown 模式
^^^^^^^^^^^^^

紧急情况下可启用系统锁定：

.. code-block:: json

   {
       "action": "lockdown",
       "data": {
           "enable": true
       },
       "username": "admin",
       "token": "token"
   }

锁定效果
^^^^^^^^

锁定模式下，只允许：

- ``server_info``
- ``register_listener``
- ``login``
- ``refresh_token``
- ``upload_file``
- ``download_file``

其他操作被拒绝，除非用户有 ``bypass_lockdown`` 权限。

使用场景
^^^^^^^^

- 发现安全漏洞
- 系统维护
- 紧急事件响应
- 阻止攻击

失败登录延迟
------------

防暴力破解
^^^^^^^^^^

登录失败后延迟响应：

.. code-block:: python

   FAILED_LOGIN_DELAY_SECONDS = 3

   # 登录失败后
   time.sleep(FAILED_LOGIN_DELAY_SECONDS)

这使得暴力破解变得不切实际。

输入验证
--------

JSON Schema 验证
^^^^^^^^^^^^^^^^

所有 API 请求使用 JSON Schema 验证：

.. code-block:: python

   data_schema = {
       "type": "object",
       "properties": {
           "username": {"type": "string", "minLength": 1},
           "password": {"type": "string", "minLength": 1}
       },
       "required": ["username", "password"],
       "additionalProperties": False
   }

   jsonschema.validate(data, data_schema)

SQL 注入防护
^^^^^^^^^^^^

使用 SQLAlchemy ORM，参数化查询：

.. code-block:: python

   # 安全
   user = session.get(User, username)

   # 不安全（已避免）
   # session.execute(f"SELECT * FROM users WHERE username = '{username}'")

路径遍历防护
^^^^^^^^^^^^

文件路径不使用用户输入，使用唯一 ID：

.. code-block:: python

   # 安全
   file_path = f"./content/{file_id}"

   # 不安全（已避免）
   # file_path = f"./content/{user_provided_filename}"

安全配置建议
------------

网络隔离
^^^^^^^^

- 使用防火墙限制访问
- 仅允许必要的端口
- 考虑使用 VPN

反向代理
^^^^^^^^

在生产环境使用反向代理（如 Nginx）：

- SSL/TLS 终止
- 负载均衡
- DDoS 防护
- 请求限流

示例配置：

.. code-block:: nginx

   server {
       listen 443 ssl;
       server_name cfms.example.com;

       ssl_certificate /path/to/cert.pem;
       ssl_certificate_key /path/to/key.pem;

       location / {
           proxy_pass http://localhost:5104;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
       }
   }

日志管理
^^^^^^^^

- 启用详细日志记录
- 定期轮换日志
- 保护日志文件访问权限
- 考虑集中日志管理

监控
^^^^

监控以下指标：

- 失败的登录尝试
- API 错误率
- 异常的流量模式
- 磁盘空间使用
- 数据库性能

备份
^^^^

- 定期备份数据库
- 备份文件存储
- 测试恢复流程
- 异地备份

更新
^^^^

- 关注安全公告
- 及时更新依赖
- 定期更新 CFMS

安全审计
--------

自我审计
^^^^^^^^

定期检查：

1. 用户权限是否合理
2. 是否有异常的审计日志
3. 密码策略是否足够严格
4. SSL 证书是否即将过期
5. 系统补丁是否最新

第三方审计
^^^^^^^^^^

考虑聘请安全专家进行：

- 渗透测试
- 代码审计
- 安全配置审查

漏洞报告
--------

如果发现安全漏洞，请通过以下方式报告：

- GitHub Issues（标记为 Security）
- 或直接联系维护者

我们会尽快响应和修复。

已知限制
--------

.. warning::

   CFMS 目前是 Alpha 阶段，未经过全面的安全审计。已知限制包括：

   - 未实现速率限制
   - 未实现 IP 封禁
   - 文件大小无硬性限制
   - 审计日志无自动清理
   - 某些错误消息可能泄露信息

在生产环境使用前，必须充分评估这些风险。

相关文档
--------

- :doc:`certtools` - 证书生成工具
- :doc:`config` - 安全相关配置
- :doc:`groups_and_rights` - 权限系统
- :doc:`access_control` - 访问控制
- :doc:`audit` - 审计日志
