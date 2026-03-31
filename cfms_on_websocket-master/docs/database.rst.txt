数据库模型
==========

CFMS 使用 SQLAlchemy ORM 管理数据库，支持 SQLite 和 MySQL。

.. contents:: 目录
   :local:
   :depth: 2

数据库架构
----------

CFMS 的数据库分为以下几个主要模块：

- **用户与权限** - 用户账户、用户组、权限管理
- **实体管理** - 文档、目录的组织结构
- **文件存储** - 物理文件和传输任务
- **访问控制** - 资源的访问规则和授权
- **审计日志** - 操作记录和安全审计
- **封禁系统** - 用户封禁管理

核心表结构
----------

用户相关表
^^^^^^^^^^

**users 表**

存储用户账户信息。

.. list-table::
   :header-rows: 1
   :widths: 20 15 50

   * - 字段
     - 类型
     - 说明
   * - username
     - VARCHAR(255)
     - 用户名（主键）
   * - pass_hash
     - TEXT
     - 密码哈希值
   * - salt
     - TEXT
     - 密码盐值
   * - passwd_last_modified
     - FLOAT
     - 密码最后修改时间
   * - nickname
     - VARCHAR(255)
     - 用户昵称
   * - last_login
     - FLOAT
     - 最后登录时间
   * - created_time
     - FLOAT
     - 创建时间
   * - secret_key
     - VARCHAR(32)
     - JWT 密钥（用户专属）

**groups 表**

存储用户组信息。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - group_name
     - VARCHAR(255)
     - 组名（主键）
   * - created_time
     - FLOAT
     - 创建时间

**user_memberships 表**

用户与组的关系。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - username
     - VARCHAR(255)
     - 用户名（外键）
   * - group_name
     - VARCHAR(255)
     - 组名（外键）
   * - start_time
     - FLOAT
     - 生效时间
   * - end_time
     - FLOAT
     - 过期时间

**user_permissions 表**

权限记录（用户或组）。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - username
     - VARCHAR(255)
     - 用户名（可选）
   * - group_name
     - VARCHAR(255)
     - 组名（可选）
   * - permission
     - VARCHAR(255)
     - 权限名称
   * - start_time
     - FLOAT
     - 生效时间
   * - end_time
     - FLOAT
     - 过期时间

实体相关表
^^^^^^^^^^

.. warning::

  由于技术设计的原因，目录和文件不得共用相同的ID，也即由全体目录ID与文档ID产生的交集应是空集。

**folders 表**

目录结构。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - VARCHAR(255)
     - 目录 ID（主键）
   * - name
     - VARCHAR(255)
     - 目录名称
   * - parent_id
     - VARCHAR(255)
     - 父目录 ID（外键）
   * - created_time
     - FLOAT
     - 创建时间
   * - access_rules
     - JSON
     - 访问规则

**documents 表**

文档元数据。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - VARCHAR(255)
     - 文档 ID（主键）
   * - title
     - VARCHAR(255)
     - 文档标题
   * - folder_id
     - VARCHAR(255)
     - 所属目录（外键）
   * - created_time
     - FLOAT
     - 创建时间
   * - access_rules
     - JSON
     - 访问规则

**document_revisions 表**

文档版本历史。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 版本 ID（主键）
   * - document_id
     - VARCHAR(255)
     - 文档 ID（外键）
   * - file_id
     - VARCHAR(255)
     - 文件 ID（外键）
   * - created_time
     - FLOAT
     - 创建时间
   * - is_active
     - BOOLEAN
     - 是否为活动版本

文件相关表
^^^^^^^^^^

**files 表**

物理文件信息。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - VARCHAR(255)
     - 文件 ID（主键）
   * - path
     - TEXT
     - 文件路径
   * - size
     - INTEGER
     - 文件大小（字节）
   * - created_time
     - FLOAT
     - 创建时间

**file_tasks 表**

文件传输任务。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - VARCHAR(255)
     - 任务 ID（主键）
   * - file_id
     - VARCHAR(255)
     - 文件 ID（外键）
   * - mode
     - INTEGER
     - 传输模式（0: 下载, 1: 上传）
   * - status
     - INTEGER
     - 任务状态
   * - start_time
     - FLOAT
     - 开始时间
   * - end_time
     - FLOAT
     - 结束时间

访问控制表
^^^^^^^^^^

**object_access_entries 表**

资源访问授权。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - object_type
     - VARCHAR(255)
     - 对象类型（documents/folders）
   * - object_id
     - VARCHAR(255)
     - 对象 ID
   * - subject_type
     - VARCHAR(255)
     - 主体类型（user/group）
   * - subject_name
     - VARCHAR(255)
     - 主体名称
   * - access_type
     - VARCHAR(255)
     - 访问类型

**document_access_rules 表**

文档访问规则。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - document_id
     - VARCHAR(255)
     - 文档 ID（外键）
   * - access_type
     - VARCHAR(255)
     - 访问类型
   * - rule_data
     - JSON
     - 规则数据

**folder_access_rules 表**

目录访问规则（结构同上）。

审计相关表
^^^^^^^^^^

**audit_entries 表**

操作审计日志。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - action
     - VARCHAR(255)
     - 操作类型
   * - username
     - VARCHAR(255)
     - 操作用户（外键）
   * - result
     - INTEGER
     - 结果状态码
   * - target
     - VARCHAR(255)
     - 操作目标
   * - data
     - JSON
     - 附加数据
   * - remote_address
     - VARCHAR(255)
     - 客户端IP
   * - timestamp
     - FLOAT
     - 时间戳

封禁相关表
^^^^^^^^^^

**user_block_entries 表**

用户封禁记录。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - username
     - VARCHAR(255)
     - 被封禁用户（外键）
   * - reason
     - TEXT
     - 封禁原因
   * - created_time
     - FLOAT
     - 封禁时间
   * - end_time
     - FLOAT
     - 解封时间

**user_block_sub_entries 表**

封禁类型详细记录。

.. list-table::
   :header-rows: 1

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - block_entry_id
     - INTEGER
     - 封禁记录 ID（外键）
   * - block_type
     - VARCHAR(255)
     - 封禁类型（read/write/move）

关系图
------

主要实体关系：

::

   users ──┬─→ user_memberships ──→ groups
           ├─→ user_permissions
           ├─→ audit_entries
           └─→ user_block_entries

   folders ──┬─→ documents ──→ document_revisions ──→ files
             └─→ folder_access_rules

   documents ──→ document_access_rules

   files ──→ file_tasks

数据库操作
----------

使用 SQLAlchemy Session
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from include.database.handler import Session
   from include.database.models.classic import User

   # 创建会话
   with Session() as session:
       # 查询
       user = session.get(User, "username")
       
       # 创建
       new_user = User(username="newuser", ...)
       session.add(new_user)
       
       # 提交
       session.commit()

配置数据库
^^^^^^^^^^

在 ``config.toml`` 中配置：

SQLite：

.. code-block:: toml

   [database]
   type = "sqlite"
   file = "app.db"

MySQL：

.. code-block:: toml

   [database]
   type = "mysql"
   host = "localhost"
   port = 3306
   username = "cfms_user"
   password = "password"
   db_name = "cfms_db"
   charset = "utf8mb4"

数据库迁移
----------

当前版本的 CFMS 在启动时自动创建表结构（如果不存在）。

备份与恢复
^^^^^^^^^^

SQLite：

.. code-block:: bash

   # 备份
   cp app.db app.db.backup

   # 恢复
   cp app.db.backup app.db

MySQL：

.. code-block:: bash

   # 备份
   mysqldump -u cfms_user -p cfms_db > backup.sql

   # 恢复
   mysql -u cfms_user -p cfms_db < backup.sql

性能优化
--------

索引建议
^^^^^^^^

建议为以下字段添加索引：

- ``users.username``（主键，已有索引）
- ``documents.folder_id``
- ``folders.parent_id``
- ``audit_entries.username``
- ``audit_entries.timestamp``

查询优化
^^^^^^^^

1. 使用 ``session.get()`` 而非 ``session.query()`` 查询主键
2. 避免 N+1 查询，使用 ``joinedload`` 或 ``selectinload``
3. 限制审计日志查询的时间范围

连接池配置
^^^^^^^^^^

对于 MySQL，可以配置连接池：

.. code-block:: python

   engine = create_engine(
       connection_string,
       pool_size=10,
       max_overflow=20,
       pool_recycle=3600
   )

故障排除
--------

数据库锁定
^^^^^^^^^^

SQLite 可能出现数据库锁定。解决方法：

1. 确保及时关闭会话
2. 使用 ``with Session()`` 自动管理
3. 考虑切换到 MySQL

外键约束错误
^^^^^^^^^^^^

检查：

1. 被引用的记录是否存在
2. 删除顺序是否正确
3. 级联删除配置

字符编码问题
^^^^^^^^^^^^

MySQL 使用 ``utf8mb4`` 以支持完整 Unicode：

.. code-block:: sql

   ALTER DATABASE cfms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

相关文档
--------

- :doc:`setup` - 数据库初始化
- :doc:`config` - 数据库配置
- :doc:`groups_and_rights` - 权限数据模型
- :doc:`access_control` - 访问控制数据模型
