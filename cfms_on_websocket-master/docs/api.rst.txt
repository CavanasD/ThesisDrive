通信协议
==================

本章节介绍 CFMS 基于 WebSocket 的通信协议，包括连接建立、消息格式和通用规范。

名词概述
--------
- **通信**：指客户端与服务器之间的一次完整的交互过程。从客户端发送请求开始，到服务器发送对请求的最终响应结束。

协议概述
--------

CFMS 使用 **WebSocket** 协议进行客户端与服务器之间的实时双向通信。

我们约定，除握手期间外，客户端和服务端用于通信的每条消息由如下数个部分组成：

1. frame_id: 长为四个字节，标记消息帧所属的一次通信。它的值由一次新通信的发起方生成，对于服务端而言，这个值取从 2 开始的递增偶数；对于客户端而言，这个值取从 1 开始的递增奇数。
2. frame_type: 长为一个字节，标记消息帧的类型。目前它有两种十进制取值： ``0`` 和 ``1``，分别指示两种类型：
    - 0: ``FrameType.PROCESS`` - **过程消息**。若一条消息不被用来指示整个通信的结束，即为过程消息。
    - 1: ``FrameType.CONCLUSION`` - **结论消息**。若一条消息同时标志着一次通信的结束，即为结论消息。一旦发出或收到了结论消息，通信即告结束。
3. payload: 长度不定，消息的实际内容。它通常以 JSON 格式编码，而后以字节形式与前两部分的数据一并封装。

客户端通过识别服务端提供的协议版本号，可以确定与目标服务器的兼容性。
协议版本号通常应在这样两种情况下增加：服务端引入了新的功能，
而这些功能需要客户端的额外适配才能得到支持；
或服务端对现有功能进行了不兼容的修改。

不同于由服务端和客户端于内部使用的协议版本号，我们还将另外约定一种格式的协议版本号，
以供区分那些发生在消息格式底层的重大更改。它们将以 ``vX`` 的形式出现，其中 X 是整数。

下述为 v1 协议。

消息格式规范
------------

请求格式
^^^^^^^^

服务端和客户端都可以主动发起通信，尽管通信根据发起方的不同其行为也有所不同，
例如由服务端和客户端发起的通信往往遵循不同的消息格式规范。

我们在此介绍由客户端发起的通信的消息格式规范。
关于由服务端发起的通信的消息格式规范，请参见 :doc:`server_events` 。

如无特殊说明，下述的请求格式将以 JSON Schema 的形式进行展示。
如果你还不知道什么是 JSON Schema，可以先 `到此 <https://json-schema.org/>`_ 阅读官方文档。

客户端请求应当遵循如下的格式：

.. code-block:: json

   {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "data": {"type": "object"},
            "username": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "token": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "nonce": {"type": "string"},
            "timestamp": {"type": "number"},
        },
        "required": ["action", "data"],
        "dependentRequired": {
            "username": ["token"],
            "token": ["username"],
        },
    }

.. list-table::
   :header-rows: 1
   :widths: 15 10 50

   * - 字段名
     - 类型
     - 说明
   * - action
     - 必需
     - 要执行的操作名称，如 ``"login"``, ``"get_document"`` 等。
       详见 :doc:`api_refs` 获取完整列表。
   * - data
     - 必需
     - 服务端完成请求所需要的数据。当请求的操作无需额外数据时，此项保持 ``{}`` 即可。
   * - username
     - 可选
     - 用户名。必须和 ``token`` 同时出现。
   * - token
     - 可选
     - JWT 认证令牌。登录后获得，用于后续请求的身份验证。
       登录和部分无需认证的操作可以为空。必须和 ``username`` 同时出现。
   * - nonce
     - 可选
     - 一段字符串，由客户端随机产生，用于防止重放攻击。每个 ``nonce`` 只能在通信中出现一次，规定 ``nonce`` 的长度不得小于 16 字符。

       对于需要提供用户凭据的请求是必要的。
   * - timestamp
     - 可选
     - 时间戳（Unix 时间），用于防止重放攻击。

       对于需要提供用户凭据的请求是必要的。

响应格式
^^^^^^^^

服务器响应遵循以下格式：

.. code-block:: json

    {
        "type": "object",
        "properties": {
            "code": { "type": "integer" },
            "message": { "type": "string" },
            "data": { "type": "object" },
            "protocol_version": { "type": "integer" }
        },
        "required": ["code", "message", "data", "protocol_version"],
        "additionalProperties": false
    }

响应字段说明：

.. list-table::
   :header-rows: 1
   :widths: 20 50

   * - 字段名
     - 说明
   * - code
     - 响应状态码。对于请求的常见操作，在能够较为准确地描述它们的情况下，状态码通常与在 HTTP 风格下的状态码一致。

       但为准确指明某操作的状态，我们也规定一些特殊的状态码，详见后文的状态码规范。
   * - message
     - 响应消息的文本描述，根据请求操作的不同会有不同的内容。这些信息通常是面向用户的，因此不应由客户端程序进行解析或处理。
   * - data
     - 响应数据，具体内容因请求类型而异。
   * - protocol_version
     - 由客户端和服务端使用的协议版本号。

状态码规范
----------

HTTP 风格状态码
^^^^^^^^^^^^^^^^

成功状态码 (2xx)
""""""""""""

成功状态码通常与 HTTP 协议在此情况下规定的状态码一致。

.. list-table::
   :header-rows: 1
   :widths: 10 20 50

   * - 代码
     - 含义
     - 说明
   * - 200
     - OK
     - 请求成功
   * - 202
     - Accepted
     - 请求已接受，需要额外操作（如两步验证）

客户端错误 (4xx)
""""""""""""

.. list-table::
   :header-rows: 1
   :widths: 10 20 50

   * - 代码
     - 含义
     - 说明
   * - 400
     - Bad Request
     - 请求格式错误或缺少必需字段
   * - 401
     - Unauthorized
     - 未认证或认证失败
   * - 403
     - Forbidden
     - 无权执行指定的操作
   * - 404
     - Not Found
     - 请求的资源不存在
   * - 409
     - Conflict
     - 资源冲突（如重名）

服务器错误 (5xx)
""""""""""""

.. list-table::
   :header-rows: 1
   :widths: 10 20 50

   * - 代码
     - 含义
     - 说明
   * - 500
     - Internal Server Error
     - 服务器内部错误

其他状态码
^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 10 20 50

    * - 代码
        - 含义
        - 说明
    * - 999
        - Lockdown
        - 服务器处于锁定模式，仅允许特定操作
    * - 4001
        - Password Requirement Not Met
        - 密码不符合安全要求，因此需要重设
    * - 4002
        - Password Expired
        - 密码过期，因此需要重设
    * - 4003
        - User Not Active
        - 用户未激活，因此无法登录

认证流程
--------

1. 获取服务器信息（可选）
^^^^^^^^^^^^^^^^^^^^^^^^^^

首次连接时，可以先查询服务器信息：

.. code-block:: json

   {
       "action": "server_info",
       "data": {},
       "username": "",
       "token": ""
   }

响应示例：

.. code-block:: json

   {
       "code": 200,
       "message": "Server information retrieved successfully",
       "data": {
           "server_name": "CFMS WebSocket Server",
           "version": "0.1.0.250919_alpha",
           "protocol_version": 3,
           "lockdown": false
       }
   }

2. 用户登录
^^^^^^^^^^^

使用用户名和密码登录：

.. code-block:: json

   {
       "action": "login",
       "data": {
           "username": "admin",
           "password": "your_password"
       },
       "username": "",
       "token": ""
   }

成功响应（无 2FA）：

.. code-block:: json

   {
       "code": 200,
       "message": "Login successful",
       "data": {
           "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
           "exp": 1699999999.0,
           "nickname": "管理员",
           "permissions": ["shutdown", "create_document", ...],
           "groups": ["sysop", "user"]
       }
   }

需要 2FA 验证响应：

.. code-block:: json

   {
       "code": 202,
       "message": "Two-factor authentication required",
       "data": {
           "method": "totp"
       }
   }

当收到 202 响应时，需要在登录请求的 ``data`` 中添加 ``2fa_token`` 字段（认证器生成的 6 位验证码）重新提交：

.. code-block:: json

   {
       "action": "login",
       "data": {
           "username": "admin",
           "password": "your_password",
           "2fa_token": "123456"
       },
       "username": "",
       "token": ""
   }

失败响应：

.. code-block:: json

   {
       "code": 401,
       "message": "Invalid credentials",
       "data": {}
   }

3. 使用令牌进行后续请求
^^^^^^^^^^^^^^^^^^^^^^^

登录成功后，使用返回的 token 进行后续操作：

.. code-block:: json

   {
       "action": "list_directory",
       "data": {
           "folder_id": "root"
       },
       "username": "admin",
       "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
   }

4. 刷新令牌
^^^^^^^^^^^

令牌默认有效期为 1 小时（3600 秒）。过期前可以刷新：

.. code-block:: json

   {
       "action": "refresh_token",
       "data": {},
       "username": "admin",
       "token": "your_current_token"
   }

响应：

.. code-block:: json

   {
       "code": 200,
       "message": "Token refreshed successfully",
       "data": {
           "token": "new_token_here",
           "exp": 1700003599.0
       }
   }

无需认证的操作
--------------

以下操作无需用户认证即可执行：

1. **server_info** - 获取服务器信息
2. **login** - 用户登录
3. **register_listener** - 注册为监听连接

文件传输
--------

CFMS 通过特殊的任务机制处理文件上传和下载。

文件下载流程
^^^^^^^^^^^^

1. 创建下载任务：

.. code-block:: json

   {
       "action": "download_file",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

2. 服务器创建任务并返回：

.. code-block:: json

   {
       "code": 200,
       "message": "Download task created",
       "data": {
           "task_id": "task_abc123",
           "file_id": "file_xyz789",
           "start_time": 1699999999.0,
           "end_time": 1700003599.0
       }
   }

3. 使用 task_id 下载文件数据（通过二进制消息）

文件上传流程
^^^^^^^^^^^^

1. 创建上传任务
2. 服务器返回 task_id
3. 使用 task_id 上传文件数据（通过二进制消息）

.. note::

   文件传输的详细实现请参考客户端示例代码。

锁定模式 (Lockdown)
-------------------

服务器可以进入"锁定模式"，此时仅允许特定操作：

- server_info
- register_listener
- login
- refresh_token
- upload_file
- download_file

拥有 ``bypass_lockdown`` 权限的用户不受锁定模式影响。

锁定模式状态可通过 ``server_info`` 查询：

.. code-block:: json

   {
       "data": {
           "lockdown": true
       }
   }

错误处理
--------

常见错误场景
^^^^^^^^^^^^

1. **JSON 格式错误**

响应：

.. code-block:: json

   {
       "code": 400,
       "message": "Invalid JSON format",
       "data": {}
   }

2. **缺少必需字段**

响应：

.. code-block:: json

   {
       "code": 400,
       "message": "Missing required field: document_id",
       "data": {
           "validator": "required",
           "validator_value": ["document_id"]
       }
   }

3. **令牌过期**

响应：

.. code-block:: json

   {
       "code": 401,
       "message": "Token expired",
       "data": {}
   }

4. **权限不足**

响应：

.. code-block:: json

   {
       "code": 403,
       "message": "Permission denied",
       "data": {}
   }

5. **资源不存在**

响应：

.. code-block:: json

   {
       "code": 404,
       "message": "Document not found",
       "data": {}
   }

最佳实践
--------

连接管理
^^^^^^^^

1. **使用连接池**：避免频繁建立和关闭连接
2. **实现重连机制**：处理网络中断
3. **心跳检测**：定期发送 ``server_info`` 保持连接活跃

令牌管理
^^^^^^^^

1. **安全存储**：不要在客户端明文存储令牌
2. **主动刷新**：在令牌过期前主动刷新
3. **失效处理**：令牌失效时重新登录

错误处理
^^^^^^^^

1. **解析状态码**：根据状态码实现不同的处理逻辑
2. **显示错误消息**：向用户展示 ``message`` 字段
3. **日志记录**：记录所有错误响应用于调试

安全建议
^^^^^^^^

1. **使用 WSS**：始终使用加密的 WebSocket 连接
2. **验证证书**：生产环境中验证 SSL 证书
3. **保护令牌**：防止令牌泄露
4. **实现超时**：为所有请求设置合理的超时时间

下一步
------

- 查看 :doc:`api_refs` 了解所有可用的 API 接口
- 学习 :doc:`groups_and_rights` 了解权限系统
- 探索 :doc:`file_management` 了解文件传输的详细实现
