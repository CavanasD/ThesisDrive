API 接口参考
====================================

本章节详细列出了 CFMS 服务端应当支持的所有 API 接口。虽然本节是根据基于 WebSocket 
的服务端实现而编写的，但其他遵循本协议的服务端也应实现这些接口，即使它们基于不同的底层进行通信。

一般地，本标准仅限定请求和响应须为 JSON 格式，并要求响应代码（ ``code`` ）和附带的数据格式
（ ``data`` ）遵循一定的要求；对于面向用户的提示信息（ ``message`` ），
由于它并非被设计为由客户端自动化处理的信息，因此不同的服务端可自行指定其内容。
本文档不会为它们指定某一特定的值。

任何被设计为由客户端自动化处理的信息都不应仅通过文本消息传递。

.. contents:: 目录
   :local:
   :depth: 2

服务器与认证 API
-----------------------------

server_info - 获取服务器信息
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取服务器的基本信息和状态。

**需要认证**：否

**请求参数**：

|no_parameter|

**响应**：

可能的响应代码：200

.. list-table:: ``data`` 结构
    :header-rows: 1
    :widths: 15 10 50

    * - 字段
      - 值类型
      - 说明
    * - server_name
      - string
      - 服务器名称
    * - version
      - string
      - 服务器版本
    * - protocol_version
      - integer
      - 协议版本号
    * - lockdown
      - boolean
      - 是否处于锁定模式

login - 用户登录
^^^^^^^^^^^^^^^^^^^

使用用户名和密码登录，获取认证令牌。

**需要认证**：否

**请求参数**:

:username: (str) 用户名。
:password: (str) 密码。
:2fa_token: (str | None) 双因素验证令牌。

**响应**:

.. list-table::
   :header-rows: 1
   :widths: 10 20 50
    * - 代码
        - 含义
        - 说明
    * - 200
        - OK
        - 登录成功
    * - 4001
        - Password Requirement Not Met
        - 密码不符合安全要求，因此需要重设
    * - 4002
        - Password Expired
        - 密码过期，因此需要重设
    * - 4003
        - User Not Active
        - 用户未激活，因此无法登录

.. list-table:: ``data`` 结构
   :widths: 20 15 65
   :header-rows: 1

   * - 字段名
     - 类型
     - 说明
   * - token
     - string
     - 认证令牌，后续 WSS 消息需在 header 或 payload 中携带。
   * - exp
     - float
     - 令牌过期的 Unix 时间戳。
   * - permissions
     - array
     - 用户拥有的权限标识符列表。

refresh_token - 刷新令牌
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

刷新用户的 JWT 令牌以延长会话时间。

**需要认证**：是

**请求**：

.. code-block:: json

   {
       "action": "refresh_token",
       "data": {},
       "username": "admin",
       "token": "current_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Token refreshed successfully",
       "data": {
           "token": "new_token_here",
           "exp": 1700003599.0
       }
   }

**错误响应**：

- ``401``: 当前令牌无效或已过期

两步验证 API
-------------------

setup_2fa - 设置两步验证
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

为当前用户设置 TOTP（基于时间的一次性密码）两步验证。

**认证要求**：是

**请求数据**：

.. list-table::
   :header-rows: 1
   :widths: 15 10 50

   * - 字段
     - 类型
     - 说明
   * - method
     - String
     - 可选。验证方法，目前仅支持 "totp"

**请求示例**：

.. code-block:: json

   {
       "action": "setup_2fa",
       "data": {},
       "username": "admin",
       "token": "your_token"
   }

**成功响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Two-factor authentication setup initiated. Please verify with your authenticator app.",
       "data": {
           "secret": "BASE32_SECRET_KEY",
           "provisioning_uri": "otpauth://totp/CFMS:admin?secret=...",
           "backup_codes": ["code1", "code2", ...]
       },
       "protocol_version": 3
   }

**字段说明**：

- ``secret``: TOTP 密钥（Base32 编码），用于手动输入
- ``provisioning_uri``: 配置 URI，可生成 QR 码供认证器应用扫描
- ``backup_codes``: 备份代码列表，用于在无法使用认证器时恢复访问

**错误响应**：

- ``400``: 两步验证已启用，需要先取消
- ``404``: 用户不存在

.. warning::

   请妥善保管备份代码！如果丢失认证器且没有备份代码，将无法登录账户。

validate_2fa - 验证两步验证
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

验证并启用两步验证。在设置两步验证后必须验证才能生效。

**认证要求**：是

**请求数据**：

.. list-table::
   :header-rows: 1
   :widths: 15 10 50

   * - 字段
     - 类型
     - 说明
   * - token
     - String
     - 认证器生成的 6 位验证码

**请求示例**：

.. code-block:: json

   {
       "action": "validate_2fa",
       "data": {
           "token": "123456"
       },
       "username": "admin",
       "token": "your_token"
   }

**成功响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Two-factor authentication enabled successfully",
       "data": {
           "method": "totp"
       },
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 两步验证未设置或已启用
- ``401``: 验证码无效
- ``404``: 用户不存在

disable_2fa - 禁用两步验证
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

禁用当前用户的两步验证。

**认证要求**：是

**请求数据**：

.. list-table::
   :header-rows: 1
   :widths: 15 10 50

   * - 字段
     - 类型
     - 说明
   * - token
     - String
     - 认证器生成的 6 位验证码或备份代码

**请求示例**：

.. code-block:: json

   {
       "action": "disable_2fa",
       "data": {
           "token": "123456"
       },
       "username": "admin",
       "token": "your_token"
   }

**成功响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Two-factor authentication disabled successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 两步验证未启用
- ``401``: 验证码无效
- ``404``: 用户不存在

cancel_2fa_setup - 取消两步验证设置
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

取消正在进行中但尚未验证的两步验证设置。

**认证要求**：是

**请求**：

.. code-block:: json

   {
       "action": "cancel_2fa_setup",
       "data": {},
       "username": "admin",
       "token": "your_token"
   }

**成功响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Two-factor authentication setup cancelled",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 没有待验证的两步验证设置或两步验证已启用
- ``404``: 用户不存在

get_2fa_status - 查询两步验证状态
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

查询当前用户的两步验证状态。

**认证要求**：是

**请求**：

.. code-block:: json

   {
       "action": "get_2fa_status",
       "data": {},
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Two-factor authentication status retrieved",
       "data": {
           "enabled": true,
           "method": "totp"
       },
       "protocol_version": 3
   }

**字段说明**：

- ``enabled``: 两步验证是否已启用
- ``method``: 验证方法（"totp" 或 null）

文档管理 API
-------------------

list_directory - 列出目录内容
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

列出指定目录下的所有文档和子目录。

**认证要求**：是

**所需权限**：对目标目录的读取权限（或 ``super_list_directory``）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - folder_id
     - String/null
     - 目录 ID。使用 null 表示根目录

**请求示例**：

.. code-block:: json

   {
       "action": "list_directory",
       "data": {
           "folder_id": null
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Directory listing successful",
       "data": {
           "parent_id": "/",
           "documents": [
               {
                   "id": "doc1",
                   "title": "Document 1",
                   "created_time": 1699999999.0,
                   "last_modified": 1699999999.0,
                   "size": 1024
               }
           ],
           "folders": [
               {
                   "id": "folder1",
                   "name": "Subfolder",
                   "created_time": 1699999999.0
               }
           ]
       },
       "protocol_version": 3
   }

**字段说明**：

- ``parent_id``: 父目录 ID，根目录的父目录为 "/"，null 表示没有父目录
- ``documents``: 文档列表，每个文档包含 id、title、created_time、last_modified 和 size
- ``folders``: 子目录列表，每个目录包含 id、name 和 created_time

**错误响应**：

- ``403``: 权限不足
- ``404``: 目录不存在

create_document - 创建文档
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

在指定目录下创建新文档并返回上传任务信息。

**认证要求**：是

**所需权限**：``create_document`` （或 ``super_create_document`` 忽略目录写权限）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - title
     - String
     - 文档标题，必填
   * - folder_id
     - String/null
     - 所属目录 ID，null 表示根目录（可选）
   * - access_rules
     - Object
     - 访问规则配置（可选）

**请求示例**：

.. code-block:: json

   {
       "action": "create_document",
       "data": {
           "title": "My Document",
           "folder_id": null,
           "access_rules": {}
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Task successfully created",
       "data": {
           "document_id": "abc123...",
           "task_data": {
               "task_id": "task123",
               "start_time": 1699999999.0,
               "end_time": 1700003599.0
           }
       },
       "protocol_version": 3
   }

**字段说明**：

- ``document_id``: 新创建的文档 ID
- ``task_data``: 文件上传任务信息
  - ``task_id``: 任务 ID，用于后续文件上传
  - ``start_time``: 任务开始时间
  - ``end_time``: 任务结束时间（通常为开始时间 + 1小时）

**错误响应**：

- ``400``: 缺少标题或设置访问规则失败
- ``403``: 权限不足或无权设置访问规则
- ``404``: 父目录不存在
- ``409``: 文档名称冲突（当配置不允许重名时）

get_document - 获取文档
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取文档的基本信息并创建下载任务。

**认证要求**：是

**所需权限**：对文档的读取权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID

**请求示例**：

.. code-block:: json

   {
       "action": "get_document",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Document successfully fetched",
       "data": {
           "document_id": "doc123",
           "title": "My Document",
           "task_data": {
               "task_id": "task456",
               "start_time": 1699999999.0,
               "end_time": 1700003599.0
           }
       },
       "protocol_version": 3
   }

**字段说明**：

- ``task_data``: 文件下载任务信息，使用 ``download_file`` 接口下载文件内容

**错误响应**：

- ``403``: 权限不足
- ``404``: 文档不存在或文档没有活动版本

get_document_info - 获取文档信息
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取文档的详细信息，包括大小、时间和访问规则。

**认证要求**：是

**所需权限**：对文档的读取权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID

**请求示例**：

.. code-block:: json

   {
       "action": "get_document_info",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Document info retrieved successfully",
       "data": {
           "document_id": "doc123",
           "parent_id": null,
           "title": "My Document",
           "size": 2048,
           "created_time": 1699999999.0,
           "last_modified": 1700000000.0,
           "access_rules": [
               {
                   "rule_id": 1,
                   "access_type": "read",
                   "rule_data": {...}
               }
           ],
           "info_code": 0
       },
       "protocol_version": 3
   }

**info_code 说明**：

- ``0``: 成功获取所有信息
- ``1``: 无权查看访问规则（access_rules 为空）

**错误响应**：

- ``403``: 权限不足
- ``404``: 文档不存在或文档没有活动版本

get_document_access_rules - 获取文档访问规则
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取文档的访问规则配置，按访问类型分组。

**认证要求**：是

**所需权限**：对文档的读取权限且拥有 ``view_access_rules`` 权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID

**请求示例**：

.. code-block:: json

   {
       "action": "get_document_access_rules",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Document access rules retrieved successfully",
       "data": {
           "read": [
               {
                   "match": "any",
                   "match_groups": [...]
               }
           ],
           "write": [...],
           "move": [...],
           "manage": [...]
       },
       "protocol_version": 3
   }

**字段说明**：

响应数据是一个字典，键为访问类型（read、write、move、manage），值为该类型的规则数据数组。

**错误响应**：

- ``403``: 权限不足或无权查看访问规则
- ``404``: 文档不存在

delete_document - 删除文档
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

删除指定文档及其所有版本。

**认证要求**：是

**所需权限**：``delete_document`` 且对文档有写权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 要删除的文档 ID

**请求示例**：

.. code-block:: json

   {
       "action": "delete_document",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Document successfully deleted",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``403``: 权限不足
- ``404``: 文档不存在
- ``500``: 删除失败（可能有正在进行的下载任务）

rename_document - 重命名文档
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改文档的标题。

**认证要求**：是

**所需权限**：``rename_document`` 且对文档有写权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID
   * - new_title
     - String
     - 新标题

**请求示例**：

.. code-block:: json

   {
       "action": "rename_document",
       "data": {
           "document_id": "doc123",
           "new_title": "Updated Title"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Document renamed successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 新标题与当前标题相同或名称冲突
- ``403``: 权限不足
- ``404``: 文档不存在

move_document - 移动文档
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

将文档移动到另一个目录。

**认证要求**：是

**所需权限**：``move`` 且对文档有移动权限，对目标目录有写权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID
   * - target_folder_id
     - String/null
     - 目标目录 ID，null 表示根目录（可选，默认不移动）

**请求示例**：

.. code-block:: json

   {
       "action": "move_document",
       "data": {
           "document_id": "doc123",
           "target_folder_id": "folder456"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Success",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 目标目录中存在同名文档或文件夹
- ``403``: 权限不足
- ``404``: 文档或目标目录不存在

upload_document - 上传文档版本
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

为已存在的文档创建新版本并返回上传任务。

**认证要求**：是

**所需权限**：对文档的写权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID

**请求示例**：

.. code-block:: json

   {
       "action": "upload_document",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Task successfully created",
       "data": {
           "task_data": {
               "task_id": "task789",
               "start_time": 1699999999.0,
               "end_time": 1700003599.0
           }
       },
       "protocol_version": 3
   }

**字段说明**：

- ``task_data``: 上传任务信息，使用 ``upload_file`` 接口上传文件内容

**错误响应**：

- ``403``: 权限不足
- ``404``: 文档不存在

set_document_rules - 设置文档访问规则
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

为文档设置访问控制规则。

**认证要求**：是

**所需权限**：``set_access_rules`` 且对文档有管理权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - document_id
     - String
     - 文档 ID
   * - access_rules
     - Object
     - 访问规则配置，键为访问类型，值为规则数组

**请求示例**：

.. code-block:: json

   {
       "action": "set_document_rules",
       "data": {
           "document_id": "doc123",
           "access_rules": {
               "read": [
                   {
                       "match": "any",
                       "match_groups": ["user"]
                   }
               ],
               "write": []
           }
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Set access rules successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 规则格式错误
- ``403``: 权限不足
- ``404``: 文档不存在

.. note::

   访问规则的详细格式请参考 :doc:`access_control`。

文件传输 API
-------------------

download_file - 下载文件
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

通过任务 ID 下载文件。此接口需要先通过 ``get_document`` 获取任务 ID。

**认证要求**：否（任务 ID 本身提供认证）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - task_id
     - String
     - 下载任务 ID

**请求示例**：

.. code-block:: json

   {
       "action": "download_file",
       "data": {
           "task_id": "task123"
       },
       "username": "",
       "token": ""
   }

**响应**：

服务器会直接通过 WebSocket 发送文件的二进制数据，不返回 JSON 响应。

**错误响应**：

- ``400``: 任务状态无效或任务时间无效
- ``404``: 任务不存在

.. note::

   此接口是锁定模式白名单操作，即使在锁定模式下也可使用。
   任务有效期为 1 小时，超时后需要重新创建任务。

upload_file - 上传文件
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

通过任务 ID 上传文件。此接口需要先通过 ``create_document`` 或 ``upload_document`` 获取任务 ID。

**认证要求**：否（任务 ID 本身提供认证）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - task_id
     - String
     - 上传任务 ID

**请求示例**：

.. code-block:: json

   {
       "action": "upload_file",
       "data": {
           "task_id": "task456"
       },
       "username": "",
       "token": ""
   }

**响应**：

服务器准备好接收文件数据后会发送确认响应，客户端应通过 WebSocket 发送文件的二进制数据。

**错误响应**：

- ``400``: 任务状态无效或任务时间无效
- ``404``: 任务不存在

.. note::

   此接口是锁定模式白名单操作。
   文件上传采用分块传输，默认块大小为 2MB。
   任务有效期为 1 小时。

create_directory - 创建目录
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

创建新目录。

**认证要求**：是

**所需权限**：``create_directory`` 或 ``super_create_directory``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - folder_id
     - String
     - 新目录的 ID
   * - name
     - String
     - 目录名称
   * - parent_id
     - String
     - 父目录 ID，"root" 表示根目录

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Directory created successfully",
       "data": {
           "folder_id": "new_folder"
       }
   }

get_directory_info - 获取目录信息
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取目录的详细信息。

**认证要求**：是

**所需权限**：对目录的读取权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - folder_id
     - String
     - 目录 ID

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Directory info retrieved successfully",
       "data": {
           "folder_id": "folder1",
           "name": "My Folder",
           "parent_id": "root",
           "created_time": 1699999999.0,
           "access_rules": []
       }
   }

delete_directory - 删除目录
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

删除目录及其所有内容。

**认证要求**：是

**所需权限**：``delete_directory``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - folder_id
     - String
     - 要删除的目录 ID

.. warning::

   删除目录会同时删除其中的所有文档和子目录！

rename_directory - 重命名目录
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改目录名称。

**认证要求**：是

**所需权限**：``rename_directory``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - folder_id
     - String
     - 目录 ID
   * - new_name
     - String
     - 新名称

move_directory - 移动目录
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

将目录移动到另一个父目录。

**认证要求**：是

**所需权限**：``move``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - folder_id
     - String
     - 目录 ID
   * - target_parent_id
     - String
     - 目标父目录 ID

用户管理 API
-------------------

list_users - 列出所有用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

列出系统中的所有用户，包括权限和组信息。

**认证要求**：是

**所需权限**：``list_users``

**请求**：

.. code-block:: json

   {
       "action": "list_users",
       "data": {},
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "List of users",
       "data": {
           "users": [
               {
                   "username": "admin",
                   "nickname": "管理员",
                   "created_time": 1699999999.0,
                   "last_login": 1700000000.0,
                   "permissions": ["shutdown", "create_user", ...],
                   "groups": ["sysop", "user"]
               },
               {
                   "username": "user1",
                   "nickname": "User 1",
                   "created_time": 1700000000.0,
                   "last_login": null,
                   "permissions": ["set_passwd"],
                   "groups": ["user"]
               }
           ]
       },
       "protocol_version": 3
   }

**字段说明**：

- ``permissions``: 用户拥有的所有权限列表（包括从组继承的权限）
- ``groups``: 用户所属的用户组列表

**错误响应**：

- ``403``: 权限不足

create_user - 创建用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

创建新用户账户，可以同时配置权限和用户组。

**认证要求**：是

**所需权限**：``create_user``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 用户名，唯一，必填
   * - password
     - String
     - 初始密码，必填
   * - nickname
     - String
     - 用户昵称（可选）
   * - permissions
     - Array
     - 权限配置数组（可选）
   * - groups
     - Array
     - 用户组配置数组（可选）

**权限配置格式**：

.. code-block:: json

   {
       "permission": "create_document",
       "start_time": 0,
       "end_time": null
   }

**用户组配置格式**：

.. code-block:: json

   {
       "group_name": "user",
       "start_time": 0,
       "end_time": null
   }

**请求示例**：

.. code-block:: json

   {
       "action": "create_user",
       "data": {
           "username": "newuser",
           "password": "secure_password",
           "nickname": "New User",
           "permissions": [
               {
                   "permission": "set_passwd",
                   "start_time": 0,
                   "end_time": null
               }
           ],
           "groups": [
               {
                   "group_name": "user",
                   "start_time": 0,
                   "end_time": null
               }
           ]
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User created successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 用户名已存在、权限或组格式错误、指定的组不存在
- ``403``: 权限不足

.. warning::

   ``create_user`` 是一个危险权限，应仅授予管理员。

delete_user - 删除用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

删除用户账户及其所有相关数据。

**认证要求**：是

**所需权限**：``delete_user``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 要删除的用户名

**请求示例**：

.. code-block:: json

   {
       "action": "delete_user",
       "data": {
           "username": "user1"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User deleted successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 尝试删除自己或缺少用户名
- ``403``: 权限不足
- ``404``: 用户不存在

.. note::

   删除用户会同时删除其组成员关系和封禁记录。

rename_user - 修改用户昵称
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改用户的昵称（显示名称）。

**认证要求**：是

**所需权限**：``rename_user`` （修改他人）或无需权限（修改自己）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 要修改的用户名
   * - nickname
     - String/null
     - 新昵称，null 表示清空昵称

**请求示例**：

.. code-block:: json

   {
       "action": "rename_user",
       "data": {
           "username": "user1",
           "nickname": "Updated Nickname"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User renamed successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 用户不存在
- ``403``: 权限不足（修改他人时需要权限）

get_user_info - 获取用户信息
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取用户的详细信息。

**认证要求**：是

**所需权限**：``get_user_info``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 目标用户名

**请求示例**：

.. code-block:: json

   {
       "action": "get_user_info",
       "data": {
           "username": "user1"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User info retrieved successfully",
       "data": {
           "username": "user1",
           "nickname": "User 1",
           "created_time": 1699999999.0,
           "last_login": 1700000000.0,
           "groups": ["user"],
           "permissions": ["set_passwd"]
       },
       "protocol_version": 3
   }

**错误响应**：

- ``403``: 权限不足
- ``404``: 用户不存在

block_user - 封禁用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

封禁用户账户，限制其对特定资源的访问。

**认证要求**：是

**所需权限**：``block``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 要封禁的用户名
   * - target
     - Object
     - 封禁目标配置
   * - block_types
     - Array
     - 封禁类型列表（如 ["read", "write"]）
   * - duration
     - Number
     - 封禁时长（秒），null 表示永久封禁

**目标配置格式**：

.. code-block:: json

   {
       "type": "all",  // 或 "document", "directory"
       "id": "doc123"  // 仅当 type 不是 "all" 时需要
   }

**请求示例**：

.. code-block:: json

   {
       "action": "block_user",
       "data": {
           "username": "user1",
           "target": {
               "type": "document",
               "id": "doc123"
           },
           "block_types": ["read", "write"],
           "duration": 3600
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User blocked successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 参数格式错误或目标资源不存在
- ``403``: 权限不足
- ``404``: 用户不存在

.. note::

   此操作每次只能添加一个封禁记录。如需添加多个封禁，应分批请求。

unblock_user - 解封用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

解除用户的封禁。

**认证要求**：是

**所需权限**：``unblock``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 要解封的用户名
   * - target
     - Object
     - 解封目标配置（格式同 block_user）
   * - block_types
     - Array
     - 要解除的封禁类型列表

**请求示例**：

.. code-block:: json

   {
       "action": "unblock_user",
       "data": {
           "username": "user1",
           "target": {
               "type": "document",
               "id": "doc123"
           },
           "block_types": ["read"]
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User unblocked successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 参数格式错误
- ``403``: 权限不足
- ``404``: 用户或封禁记录不存在

get_user_avatar - 获取用户头像
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取用户的头像图片数据。

**认证要求**：是

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 目标用户名

**请求示例**：

.. code-block:: json

   {
       "action": "get_user_avatar",
       "data": {
           "username": "user1"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Avatar retrieved successfully",
       "data": {
           "avatar_data": "base64_encoded_image_data",
           "mime_type": "image/png"
       },
       "protocol_version": 3
   }

**错误响应**：

- ``404``: 用户不存在或未设置头像

set_user_avatar - 设置用户头像
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

设置用户的头像图片。

**认证要求**：是

**所需权限**：``set_user_avatar`` （设置他人）或无需权限（设置自己）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 目标用户名
   * - avatar_data
     - String
     - Base64 编码的图片数据

**请求示例**：

.. code-block:: json

   {
       "action": "set_user_avatar",
       "data": {
           "username": "user1",
           "avatar_data": "iVBORw0KGgoAAAANSUhEUgAAAAUA..."
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Avatar set successfully",
       "data": {
           "avatar_id": "avatar123"
       },
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 图片数据无效或格式不支持
- ``403``: 权限不足
- ``404``: 用户不存在

.. note::

   支持的图片格式：JPEG, PNG, GIF, BMP, WebP等常见格式。

change_user_groups - 修改用户组
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改用户所属的用户组。

**认证要求**：是

**所需权限**：``change_user_groups``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 目标用户名
   * - groups
     - Array
     - 用户组配置数组

**用户组配置格式**：

.. code-block:: json

   {
       "group_name": "sysop",
       "start_time": 0,
       "end_time": null
   }

**请求示例**：

.. code-block:: json

   {
       "action": "change_user_groups",
       "data": {
           "username": "user1",
           "groups": [
               {
                   "group_name": "user",
                   "start_time": 0,
                   "end_time": null
               },
               {
                   "group_name": "developer",
                   "start_time": 1699999999.0,
                   "end_time": 1700003599.0
               }
           ]
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "User groups changed successfully",
       "data": {},
       "protocol_version": 3
   }

**字段说明**：

- ``start_time``: 生效时间（Unix 时间戳），0 或 null 表示立即生效
- ``end_time``: 过期时间（Unix 时间戳），null 表示永不过期

**错误响应**：

- ``400``: 组配置格式错误或指定的组不存在
- ``403``: 权限不足
- ``404``: 用户不存在

set_passwd - 修改密码
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改用户密码。

**认证要求**：是

**所需权限**：``set_passwd`` （修改自己）或 ``super_set_passwd`` （修改他人）

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - username
     - String
     - 要修改密码的用户名
   * - old_password
     - String
     - 当前密码（修改自己时必需）
   * - new_password
     - String
     - 新密码

**请求示例**：

.. code-block:: json

   {
       "action": "set_passwd",
       "data": {
           "username": "user1",
           "old_password": "current_password",
           "new_password": "new_secure_password"
       },
       "username": "user1",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Password changed successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 缺少必需字段、旧密码错误或新密码不符合要求
- ``403``: 权限不足
- ``404``: 用户不存在

.. note::

   密码要求由服务器配置文件中的安全策略决定，可能包括最小长度、必须包含的字符类型等。


change_user_groups - 修改用户组
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改用户所属的用户组。

**认证要求**：是

**所需权限**：``change_user_groups``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - target_username
     - String
     - 目标用户名
   * - groups
     - Array
     - 用户组配置数组

**组配置格式**：

.. code-block:: json

   {
       "group_name": "sysop",
       "start_time": 0,
       "end_time": null
   }

- ``start_time``: 生效时间（Unix 时间戳），0 或 null 表示立即生效
- ``end_time``: 过期时间（Unix 时间戳），null 表示永不过期

block_user - 封禁用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

封禁用户账户。

**认证要求**：是

**所需权限**：``block``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - target_username
     - String
     - 要封禁的用户名
   * - reason
     - String
     - 封禁原因（可选）
   * - end_time
     - Float
     - 解封时间（Unix 时间戳），null 表示永久封禁

unblock_user - 解封用户
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

解除用户封禁。

**认证要求**：是

**所需权限**：``unblock``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - target_username
     - String
     - 要解封的用户名

用户组管理 API
-------------------

list_groups - 列出用户组
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

列出系统中的所有用户组及其信息。

**认证要求**：是

**所需权限**：``list_groups``

**请求**：

.. code-block:: json

   {
       "action": "list_groups",
       "data": {},
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "List of groups",
       "data": {
           "groups": [
               {
                   "name": "user",
                   "display_name": "普通用户",
                   "permissions": ["set_passwd"],
                   "members": ["user1", "user2"]
               },
               {
                   "name": "sysop",
                   "display_name": "系统管理员",
                   "permissions": ["shutdown", "create_user", ...],
                   "members": ["admin"]
               }
           ]
       },
       "protocol_version": 3
   }

**字段说明**：

- ``name``: 组名（唯一标识符）
- ``display_name``: 显示名称
- ``permissions``: 组拥有的所有权限列表
- ``members``: 组成员用户名列表

**错误响应**：

- ``403``: 权限不足

create_group - 创建用户组
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

创建新用户组，可以同时配置权限。

**认证要求**：是

**所需权限**：``create_group``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - group_name
     - String
     - 用户组名称（唯一），必填
   * - display_name
     - String/null
     - 显示名称（可选）
   * - permissions
     - Array
     - 权限配置数组（可选）

**权限配置格式**：

.. code-block:: json

   {
       "permission": "create_document",
       "start_time": 0,
       "end_time": null
   }

**请求示例**：

.. code-block:: json

   {
       "action": "create_group",
       "data": {
           "group_name": "moderator",
           "display_name": "内容审核员",
           "permissions": [
               {
                   "permission": "delete_document",
                   "start_time": 0,
                   "end_time": null
               }
           ]
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Group created successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 组名已存在或权限配置格式错误
- ``403``: 权限不足

.. warning::

   ``create_group`` 是一个危险权限，应仅授予管理员。

delete_group - 删除用户组
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

删除用户组及其所有权限配置。

**认证要求**：是

**所需权限**：``delete_group``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - group_name
     - String
     - 要删除的用户组名称

**请求示例**：

.. code-block:: json

   {
       "action": "delete_group",
       "data": {
           "group_name": "moderator"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Group deleted successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``403``: 权限不足
- ``404``: 用户组不存在

.. warning::

   删除用户组会影响所有属于该组的用户，他们将失去从该组继承的所有权限！

rename_group - 重命名用户组
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改用户组的名称或显示名称。

**认证要求**：是

**所需权限**：``rename_group``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - group_name
     - String
     - 当前组名
   * - new_name
     - String
     - 新组名（可选）
   * - new_display_name
     - String/null
     - 新显示名称（可选）

**请求示例**：

.. code-block:: json

   {
       "action": "rename_group",
       "data": {
           "group_name": "moderator",
           "new_name": "content_moderator",
           "new_display_name": "内容管理员"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Group renamed successfully",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``400``: 新组名已存在或未提供任何修改
- ``403``: 权限不足
- ``404``: 用户组不存在

.. note::

   可以只修改组名、只修改显示名称，或同时修改两者。

get_group_info - 获取用户组信息
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

获取用户组的详细信息，包括权限和成员。

**认证要求**：是

**所需权限**：``get_group_info``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - group_name
     - String
     - 用户组名称

**请求示例**：

.. code-block:: json

   {
       "action": "get_group_info",
       "data": {
           "group_name": "sysop"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Group info retrieved successfully",
       "data": {
           "group_name": "sysop",
           "display_name": "系统管理员",
           "created_time": 1699999999.0,
           "permissions": [
               {
                   "permission": "shutdown",
                   "start_time": 0,
                   "end_time": null
               },
               {
                   "permission": "create_document",
                   "start_time": 0,
                   "end_time": null
               }
           ],
           "members": ["admin"]
       },
       "protocol_version": 3
   }

**错误响应**：

- ``403``: 权限不足
- ``404``: 用户组不存在

change_group_permissions - 修改用户组权限
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

修改用户组的权限配置，会替换现有的所有权限。

**认证要求**：是

**所需权限**：``set_group_permissions``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - group_name
     - String
     - 用户组名称
   * - permissions
     - Array
     - 权限配置数组

**权限配置格式**：

.. code-block:: json

   {
       "permission": "create_document",
       "start_time": 0,
       "end_time": null
   }

**请求示例**：

.. code-block:: json

   {
       "action": "change_group_permissions",
       "data": {
           "group_name": "moderator",
           "permissions": [
               {
                   "permission": "delete_document",
                   "start_time": 0,
                   "end_time": null
               },
               {
                   "permission": "rename_document",
                   "start_time": 0,
                   "end_time": 1700003599.0
               }
           ]
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Group permissions changed successfully",
       "data": {},
       "protocol_version": 3
   }

**字段说明**：

- ``start_time``: 生效时间（Unix 时间戳），0 表示立即生效
- ``end_time``: 过期时间（Unix 时间戳），null 表示永不过期

**错误响应**：

- ``400``: 权限配置格式错误
- ``403``: 权限不足
- ``404``: 用户组不存在

.. warning::

   此操作会完全替换组的现有权限配置！如果只想添加或删除特定权限，请先获取现有权限，修改后再提交。

访问控制 API
-------------------

grant_access - 授予访问权限
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

为用户或用户组授予对特定资源的访问权限，支持时间限制。

**认证要求**：是

**所需权限**：``manage_access`` 且对目标资源拥有相应的访问权限

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - entity_type
     - String
     - 授权对象类型："user" 或 "group"
   * - entity_identifier
     - String
     - 用户名或组名
   * - target_type
     - String
     - 目标类型："document" 或 "directory"
   * - target_identifier
     - String
     - 目标 ID
   * - access_types
     - Array
     - 访问类型列表（如 ["read", "write"]）
   * - start_time
     - Number
     - 生效时间（Unix 时间戳），最小 0
   * - end_time
     - Number
     - 过期时间（Unix 时间戳），可选

**请求示例**：

.. code-block:: json

   {
       "action": "grant_access",
       "data": {
           "entity_type": "user",
           "entity_identifier": "user1",
           "target_type": "document",
           "target_identifier": "doc123",
           "access_types": ["read", "write"],
           "start_time": 0,
           "end_time": null
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Success",
       "data": {},
       "protocol_version": 3
   }

**字段说明**：

- ``access_types``: 可以包含多个访问类型，每个类型会创建一条单独的访问记录
- ``start_time``: 0 表示立即生效
- ``end_time``: null 表示永不过期

**错误响应**：

- ``400``: start_time 晚于 end_time、实体或目标不存在
- ``403``: 权限不足或对目标资源没有相应的访问权限
- ``404``: 实体或目标不存在

view_access_entries - 查看访问记录
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

查看用户、组或资源的访问控制记录。

**认证要求**：是

**所需权限**：``view_access_entries``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - object_type
     - String
     - 对象类型："user", "group", "document" 或 "directory"
   * - object_identifier
     - String
     - 对象标识符（用户名、组名或资源 ID）

**请求示例 1 - 查看用户的访问权限**：

.. code-block:: json

   {
       "action": "view_access_entries",
       "data": {
           "object_type": "user",
           "object_identifier": "user1"
       },
       "username": "admin",
       "token": "your_token"
   }

**请求示例 2 - 查看文档的访问权限**：

.. code-block:: json

   {
       "action": "view_access_entries",
       "data": {
           "object_type": "document",
           "object_identifier": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Success",
       "data": {
           "result": [
               {
                   "id": 1,
                   "entity_type": "user",
                   "entity_identifier": "user1",
                   "target_type": "document",
                   "target_identifier": "doc123",
                   "access_type": "read",
                   "start_time": 0,
                   "end_time": null
               }
           ]
       },
       "protocol_version": 3
   }

**字段说明**：

- 当 ``object_type`` 为 "user" 或 "group" 时，返回该实体拥有的所有访问权限
- 当 ``object_type`` 为 "document" 或 "directory" 时，返回授予该资源的所有访问权限
- ``result``: 访问记录数组，每条记录包含完整的访问控制信息

**错误响应**：

- ``403``: 权限不足

.. note::

   此 API 用于查看通过 ``grant_access`` 创建的显式访问记录，不包括通过访问规则（access_rules）计算出的权限。

系统管理 API
-------------------

lockdown - 锁定系统
^^^^^^^^^^^^^^^^^^^^^^^

启用或禁用系统锁定模式。锁定模式下，只有白名单内的操作和拥有 ``bypass_lockdown`` 权限的用户可以操作。

**认证要求**：是

**所需权限**：``apply_lockdown``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - status
     - Boolean
     - true 启用锁定，false 禁用锁定

**请求示例**：

.. code-block:: json

   {
       "action": "lockdown",
       "data": {
           "status": true
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Success",
       "data": {},
       "protocol_version": 3
   }

**副作用**：

- 启用锁定模式时，所有正在进行的文件传输任务将被立即终止（end_time 被设置为当前时间）
- 系统会向所有已注册的监听连接广播锁定状态变更消息

**锁定模式白名单**：

以下操作在锁定模式下仍可使用：

- server_info
- register_listener
- login
- refresh_token
- validate_2fa
- upload_file
- download_file

**错误响应**：

- ``401``: 认证失败
- ``403``: 权限不足

.. warning::

   启用锁定模式会终止所有正在进行的文件传输任务！

view_audit_logs - 查看审计日志
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

查看系统审计日志，支持分页和过滤。

**认证要求**：是

**所需权限**：``view_audit_logs``

**请求数据**：

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - offset
     - Integer
     - 偏移量，用于分页（可选，默认 0，最小 0）
   * - count
     - Integer
     - 返回记录数量（可选，默认 50，最小 0，最大 100）
   * - filters
     - Array
     - 操作类型过滤列表（可选，空数组表示不过滤）

**请求示例**：

.. code-block:: json

   {
       "action": "view_audit_logs",
       "data": {
           "offset": 0,
           "count": 50,
           "filters": ["login", "create_user"]
       },
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Success",
       "data": {
           "total": 1000,
           "entries": [
               {
                   "id": 1,
                   "action": "login",
                   "username": "admin",
                   "target": "admin",
                   "data": null,
                   "result": 0,
                   "remote_address": "127.0.0.1",
                   "logged_time": 1699999999.0
               }
           ]
       },
       "protocol_version": 3
   }

**字段说明**：

- ``total``: 符合过滤条件的总记录数（用于分页）
- ``entries``: 审计日志条目数组
  - ``id``: 日志条目 ID
  - ``action``: 执行的操作
  - ``username``: 执行操作的用户
  - ``target``: 操作目标（可能为 null）
  - ``data``: 附加数据（可能为 null）
  - ``result``: 操作结果代码（0 表示成功）
  - ``remote_address``: 客户端 IP 地址
  - ``logged_time``: 日志记录时间

**错误响应**：

- ``401``: 认证失败
- ``403``: 权限不足

shutdown - 关闭服务器
^^^^^^^^^^^^^^^^^^^^^^^

关闭 CFMS 服务器。

**认证要求**：是

**所需权限**：``shutdown``

**请求**：

.. code-block:: json

   {
       "action": "shutdown",
       "data": {},
       "username": "admin",
       "token": "your_token"
   }

**响应**：

.. code-block:: json

   {
       "code": 200,
       "message": "Server is shutting down",
       "data": {},
       "protocol_version": 3
   }

**错误响应**：

- ``403``: 权限不足或认证失败

.. danger::

   此操作会立即关闭服务器，所有活动连接将被断开！不可撤销！


常见状态码
----------

所有 API 可能返回的通用状态码：

成功状态码 (2xx)
^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 10 30 40

   * - 代码
     - 含义
     - 使用场景
   * - 200
     - OK
     - 请求成功，返回数据
   * - 202
     - Accepted
     - 请求已接受，需要额外操作（如 login 需要两步验证）

错误状态码
^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 10 30 40

   * - 代码
     - 含义
     - 可能原因
   * - 400
     - Bad Request
     - JSON 格式错误、缺少必需字段、字段类型错误
   * - 401
     - Unauthorized
     - 未提供认证信息、令牌无效或过期
   * - 403
     - Forbidden
     - 权限不足、密码需更改
   * - 404
     - Not Found
     - 请求的资源（文档、目录、用户等）不存在
   * - 409
     - Conflict
     - 资源冲突（如ID重复、名称重复）
   * - 500
     - Internal Server Error
     - 服务器内部错误，查看日志获取详细信息
   * - 999
     - Lockdown
     - 服务器处于锁定模式

相关文档
--------

- :doc:`api` - WebSocket 通信协议详解
- :doc:`groups_and_rights` - 权限系统说明
- :doc:`access_control` - 访问控制规则详解
- :doc:`file_management` - 文件传输详解
