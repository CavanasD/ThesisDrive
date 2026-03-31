文件管理
========

CFMS 实现了基于任务的文件传输机制，支持大文件的分块传输。

.. contents:: 目录
   :local:
   :depth: 2

文件系统架构
------------

文档与文件分离
^^^^^^^^^^^^^^

CFMS 将文档（Document）和物理文件（File）分离：

- **Document**：业务层概念，包含标题、所属目录等元数据
- **File**：存储层概念，实际的文件内容存储
- **DocumentRevision**：连接两者，一个文档可以有多个版本

这种设计的优势：

1. 支持文档版本历史
2. 可以多个文档共享同一个物理文件
3. 便于实现文件去重

文件存储
^^^^^^^^

文件默认存储在 ``./content/`` 目录下，每个文件有唯一的 ID 作为标识。

存储路径由 ``File.path`` 字段记录。

文件传输机制
------------

任务系统
^^^^^^^^

文件传输通过任务（Task）系统实现：

1. 客户端请求创建传输任务
2. 服务器创建 ``FileTask`` 记录并返回任务 ID
3. 客户端使用任务 ID 进行实际的文件传输
4. 任务有有效期（默认 1 小时）

传输模式
^^^^^^^^

- **模式 0（下载）**：从服务器下载文件
- **模式 1（上传）**：向服务器上传文件

任务状态
^^^^^^^^

- **0**：待处理
- **1**：进行中
- **2**：已完成
- **3**：失败

文件下载
--------

下载流程
^^^^^^^^

1. **创建下载任务**

.. code-block:: json

   {
       "action": "download_file",
       "data": {
           "document_id": "doc123"
       },
       "username": "user",
       "token": "token"
   }

响应：

.. code-block:: json

   {
       "code": 200,
       "message": "Download task created",
       "data": {
           "task_id": "task_abc",
           "file_id": "file_xyz",
           "start_time": 1699999999.0,
           "end_time": 1700003599.0
       }
   }

2. **下载文件内容**

使用返回的 ``task_id`` 通过 WebSocket 的二进制消息下载文件。

文件以分块方式传输，块大小由配置文件中的 ``file_chunk_size`` 决定（默认 2MB）。

权限检查
^^^^^^^^

下载文件需要：

- 对文档有 ``read`` 访问权限
- 通过文档的访问规则检查

下载示例
^^^^^^^^

.. code-block:: python

   import websockets
   import json
   import ssl

   ssl_context = ssl.create_default_context()
   ssl_context.check_hostname = False
   ssl_context.verify_mode = ssl.CERT_NONE

   async with websockets.connect('wss://localhost:5104', ssl=ssl_context) as ws:
       # 创建下载任务
       request = {
           "action": "download_file",
           "data": {"document_id": "doc123"},
           "username": "user",
           "token": "token"
       }
       await ws.send(json.dumps(request))
       response = json.loads(await ws.recv())
       
       task_id = response['data']['task_id']
       
       # 下载文件（具体实现取决于协议）
       # ...

文件上传
--------

上传流程
^^^^^^^^

1. **创建文档和上传任务**

.. code-block:: json

   {
       "action": "upload_document",
       "data": {
           "document_id": "doc123"
       },
       "username": "user",
       "token": "token"
   }

响应包含上传任务信息。

2. **上传文件内容**

使用返回的 ``task_id`` 通过 WebSocket 的二进制消息上传文件。

权限检查
^^^^^^^^

上传文件需要：

- 对文档有 ``write`` 访问权限
- 对文档所在目录有访问权限

上传示例
^^^^^^^^

.. code-block:: python

   async with websockets.connect('wss://localhost:5104', ssl=ssl_context) as ws:
       # 创建上传任务
       request = {
           "action": "upload_document",
           "data": {"document_id": "doc123"},
           "username": "user",
           "token": "token"
       }
       await ws.send(json.dumps(request))
       response = json.loads(await ws.recv())
       
       task_id = response['data']['task_id']
       
       # 上传文件（具体实现取决于协议）
       # ...

文件任务管理
------------

FileTask 模型
^^^^^^^^^^^^^

.. code-block:: python

   class FileTask:
       id: str              # 任务 ID（自动生成）
       file_id: str         # 关联的文件 ID
       mode: int            # 传输模式（0: 下载, 1: 上传）
       status: int          # 任务状态
       start_time: float    # 开始时间
       end_time: float      # 结束时间

创建任务
^^^^^^^^

.. code-block:: python

   from include.handlers.document import create_file_task
   from include.database.models.file import File

   # 创建下载任务
   task_info = create_file_task(file, transfer_mode=0)

   # task_info 包含:
   # - task_id: 任务 ID
   # - start_time: 开始时间
   # - end_time: 结束时间（开始时间 + 1小时）

任务有效期
^^^^^^^^^^

任务的有效期由 ``FILE_TASK_DEFAULT_DURATION_SECONDS`` 常量定义，默认为 3600 秒（1 小时）。

过期的任务应该自动清理，但当前版本可能需要手动清理。

文档版本管理
------------

创建新版本
^^^^^^^^^^

当上传文件到已存在的文档时，会创建新的版本：

.. code-block:: python

   # 创建新版本
   new_revision = DocumentRevision(
       document_id=document.id,
       file_id=new_file.id
   )
   
   # 将旧版本标记为非活动
   for revision in document.revisions:
       revision.is_active = False
   
   # 新版本标记为活动
   new_revision.is_active = True

获取最新版本
^^^^^^^^^^^^

.. code-block:: python

   document = session.get(Document, "doc123")
   latest_revision = document.get_latest_revision()
   file = latest_revision.file

查看版本历史
^^^^^^^^^^^^

.. code-block:: python

   document = session.get(Document, "doc123")
   for revision in document.revisions:
       print(f"版本 {revision.id}: {revision.created_time}")

文件存储优化
------------

文件去重
^^^^^^^^

虽然当前版本未实现，但架构支持文件去重：

1. 计算文件哈希
2. 检查是否已有相同哈希的文件
3. 如有，复用现有文件而不是创建新文件

实现示例：

.. code-block:: python

   import hashlib

   def get_file_hash(file_path):
       hash_md5 = hashlib.md5()
       with open(file_path, "rb") as f:
           for chunk in iter(lambda: f.read(4096), b""):
               hash_md5.update(chunk)
       return hash_md5.hexdigest()

清理孤儿文件
^^^^^^^^^^^^

定期清理没有被任何 ``DocumentRevision`` 引用的文件：

.. code-block:: python

   from include.database.handler import Session
   from include.database.models.file import File
   from include.database.models.entity import DocumentRevision
   import os

   with Session() as session:
       # 查找所有被引用的文件ID
       referenced_files = set(
           r.file_id for r in session.query(DocumentRevision).all()
       )
       
       # 查找所有文件
       all_files = session.query(File).all()
       
       # 删除未被引用的文件
       for file in all_files:
           if file.id not in referenced_files:
               if os.path.exists(file.path):
                   os.remove(file.path)
               session.delete(file)
       
       session.commit()

文件传输配置
------------

分块大小
^^^^^^^^

在 ``config.toml`` 中配置：

.. code-block:: toml

   [server]
   file_chunk_size = 2097152  # 2MB

较大的分块提高传输效率，但可能因客户端限制失败。
推荐值：1MB - 4MB

任务有效期
^^^^^^^^^^

在 ``include/constants.py`` 中定义：

.. code-block:: python

   FILE_TASK_DEFAULT_DURATION_SECONDS = 3600  # 1 hour

可以根据需要调整。

安全考虑
--------

任务验证
^^^^^^^^

- 任务 ID 使用安全的随机字符串生成
- 任务有时间限制，防止长期有效
- 下载任务检查用户权限

路径安全
^^^^^^^^

- 文件路径不应包含 ``..`` 等危险字符
- 文件存储在受限目录下
- 文件名使用 ID 而非用户提供的名称

大小限制
^^^^^^^^

考虑添加文件大小限制：

.. code-block:: python

   MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

   if file_size > MAX_FILE_SIZE:
       raise ValueError("File too large")

故障排除
--------

文件上传失败
^^^^^^^^^^^^

检查：

1. 任务是否过期
2. 文件大小是否超过限制
3. 服务器磁盘空间是否充足
4. 网络连接是否稳定
5. 分块大小配置是否合适

文件下载失败
^^^^^^^^^^^^

检查：

1. 文档是否存在
2. 用户是否有读取权限
3. 文件是否存在于磁盘
4. 任务是否已过期

文件丢失
^^^^^^^^

可能原因：

1. 磁盘故障
2. 误删除
3. 数据库与文件系统不同步

解决：

- 定期备份
- 检查文件系统完整性
- 同步数据库和文件系统

相关文档
--------

- :doc:`api_refs` - 文件传输相关 API
- :doc:`config` - 文件传输配置
- :doc:`database` - File 和 FileTask 数据模型
