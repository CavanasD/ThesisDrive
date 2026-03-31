权限与用户组
===================================

CFMS 实现了完整的基于角色的访问控制（RBAC）系统，通过权限和用户组的组合来管理用户对资源的访问。

.. contents:: 目录
   :local:
   :depth: 2

权限系统概述
------------

权限本质
^^^^^^^^

在 CFMS 中，权限（Permission）是一个字符串标识符，表示用户可以执行的特定操作。
权限通过服务端的内部逻辑实现复杂的访问控制。

权限特点：

- **细粒度控制**：每个操作都有对应的权限要求
- **时间限制**：权限可以设置生效时间和过期时间
- **灵活组合**：权限可以直接授予用户，也可以通过用户组继承

权限来源
^^^^^^^^

用户的权限来自两个途径：

1. **直接权限**：直接授予给用户的权限
2. **组权限**：用户通过所属用户组继承的权限

最终权限是两者的并集。

权限分类
--------

系统管理权限
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - shutdown
     - 关闭服务器
   * - manage_system
     - 系统管理权限
   * - apply_lockdown
     - 启用/禁用系统锁定模式
   * - bypass_lockdown
     - 在锁定模式下不受限制

文档管理权限
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - create_document
     - 在有权访问的目录创建文档
   * - super_create_document
     - 在任何目录创建文档
   * - delete_document
     - 删除文档
   * - rename_document
     - 重命名文档
   * - move
     - 移动文档或目录

目录管理权限
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - create_directory
     - 在有权访问的目录创建子目录
   * - super_create_directory
     - 在任何位置创建目录
   * - list_directory
     - 列出目录内容
   * - super_list_directory
     - 列出任何目录内容
   * - delete_directory
     - 删除目录
   * - rename_directory
     - 重命名目录

用户管理权限
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - create_user
     - 创建新用户
   * - delete_user
     - 删除用户
   * - rename_user
     - 修改用户名
   * - get_user_info
     - 查看用户信息
   * - list_users
     - 列出所有用户
   * - change_user_groups
     - 修改用户所属组
   * - set_passwd
     - 修改自己的密码
   * - super_set_passwd
     - 修改任何用户的密码
   * - block
     - 封禁用户
   * - unblock
     - 解除用户封禁

用户组管理权限
^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - list_groups
     - 列出所有用户组
   * - create_group
     - 创建新用户组
   * - delete_group
     - 删除用户组
   * - rename_group
     - 重命名用户组
   * - get_group_info
     - 查看用户组信息
   * - set_group_permissions
     - 修改用户组权限

访问控制权限
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - view_access_rules
     - 查看资源的访问规则
   * - set_access_rules
     - 设置资源的访问规则
   * - manage_access
     - 管理访问权限
   * - view_access_entries
     - 查看访问记录
   * - grant_access
     - 授予访问权限

审计与监控权限
^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 60

   * - 权限名称
     - 说明
   * - view_audit_logs
     - 查看审计日志

用户组系统
----------

用户组定义
^^^^^^^^^^

用户组（User Group）是一组权限的集合。用户通过加入用户组来获得该组的所有权限。

用户组的特点：

- **权限继承**：用户自动获得所属组的所有权限
- **多组成员**：一个用户可以同时属于多个组
- **时间控制**：组成员身份可以设置生效和过期时间
- **动态权限**：修改组权限会立即影响所有成员

默认用户组
^^^^^^^^^^

CFMS 系统包含两个默认用户组：

**user 组**

- **用途**：基础用户组，所有用户默认应加入
- **默认权限**：
  
  - ``set_passwd`` - 修改自己的密码

**sysop 组**

- **用途**：系统管理员组，拥有完整的系统权限
- **默认权限**：几乎所有系统权限（见初始化代码）

.. warning::

   不要删除默认用户组！系统的某些逻辑依赖于这些组的存在。

数据库结构
----------

users 表
^^^^^^^^

存储用户基本信息：

.. list-table::
   :header-rows: 1
   :widths: 20 15 50

   * - 字段名
     - 类型
     - 说明
   * - username
     - VARCHAR(255)
     - 用户名（主键）
   * - pass_hash
     - TEXT
     - 密码哈希
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
     - 账户创建时间
   * - secret_key
     - VARCHAR(32)
     - 用户专属JWT密钥

groups 表
^^^^^^^^^

存储用户组信息：

.. list-table::
   :header-rows: 1
   :widths: 20 15 50

   * - 字段名
     - 类型
     - 说明
   * - group_name
     - VARCHAR(255)
     - 组名（主键）
   * - created_time
     - FLOAT
     - 创建时间

user_memberships 表
^^^^^^^^^^^^^^^^^^^

存储用户与组的关系：

.. list-table::
   :header-rows: 1
   :widths: 20 15 50

   * - 字段名
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
     - 生效时间（NULL表示立即）
   * - end_time
     - FLOAT
     - 过期时间（NULL表示永不过期）

user_permissions 表
^^^^^^^^^^^^^^^^^^^

存储用户和组的权限：

.. list-table::
   :header-rows: 1
   :widths: 20 15 50

   * - 字段名
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键
   * - username
     - VARCHAR(255)
     - 用户名（可选，用户权限）
   * - group_name
     - VARCHAR(255)
     - 组名（可选，组权限）
   * - permission
     - VARCHAR(255)
     - 权限名称
   * - start_time
     - FLOAT
     - 生效时间
   * - end_time
     - FLOAT
     - 过期时间

.. note::

   每条记录要么属于用户（username 非空），要么属于组（group_name 非空），不能同时为空或同时非空。

权限检查机制
------------

权限获取流程
^^^^^^^^^^^^

当系统需要检查用户权限时：

1. **获取直接权限**：查询 ``user_permissions`` 表中该用户的所有有效权限
2. **获取组权限**：查询用户所属的所有有效组
3. **获取组的权限**：查询这些组在 ``user_permissions`` 表中的权限
4. **合并权限**：将直接权限和组权限合并，去重

时间检查
^^^^^^^^

对于带有时间限制的权限和组成员身份：

- **生效时间**：``start_time`` 为 ``NULL`` 或 ``0`` 表示立即生效，否则在指定时间后生效
- **过期时间**：``end_time`` 为 ``NULL`` 表示永不过期，否则在指定时间后失效
- **当前有效**：``start_time <= 当前时间`` 且 ``(end_time is NULL or end_time >= 当前时间)``

权限检查示例
^^^^^^^^^^^^

检查用户是否有 ``create_document`` 权限：

.. code-block:: python

   with Session() as session:
       user = session.get(User, username)
       if "create_document" in user.all_permissions:
           # 用户有该权限
           pass
       else:
           # 用户没有该权限
           pass

``user.all_permissions`` 属性自动返回用户的所有有效权限（包括直接权限和组权限）。

用户组管理
----------

创建用户组
^^^^^^^^^^

.. code-block:: python

   from include.util.group import create_group

   create_group(
       group_name="editors",
       permissions=[
           {"permission": "create_document"},
           {"permission": "rename_document"},
           {"permission": "delete_document", "end_time": 1704067200},
       ],
   )

修改用户组权限
^^^^^^^^^^^^^^

通过 ``change_group_permissions`` API 修改：

.. code-block:: json

   {
       "action": "change_group_permissions",
       "data": {
           "group_name": "editors",
           "permissions": [
               {
                   "permission": "create_document",
                   "start_time": 0,
                   "end_time": null
               }
           ]
       },
       "username": "admin",
       "token": "your_token"
   }

将用户加入组
^^^^^^^^^^^^

通过 ``change_user_groups`` API：

.. code-block:: json

   {
       "action": "change_user_groups",
       "data": {
           "target_username": "user1",
           "groups": [
               {
                   "group_name": "editors",
                   "start_time": 0,
                   "end_time": null
               },
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

授予直接权限
^^^^^^^^^^^^

可以通过数据库直接操作（未来可能提供 API）：

.. code-block:: python

   from include.database.models.classic import UserPermission
   from include.database.handler import Session

   with Session() as session:
       perm = UserPermission(
           username="user1",
           permission="special_permission",
           start_time=0,
           end_time=None
       )
       session.add(perm)
       session.commit()

权限设计最佳实践
----------------

1. **最小权限原则**

   只授予用户完成工作所需的最小权限集。

2. **使用用户组**

   通过用户组管理权限，而不是为每个用户单独配置。这样更易于维护。

3. **定期审查**

   定期检查用户权限，撤销不再需要的权限。

4. **使用时间限制**

   对临时权限设置过期时间，避免权限过度积累。

5. **分离职责**

   不同职责的操作使用不同的权限，避免权限过于宽泛。

6. **文档化权限**

   记录每个权限的用途和授予理由。

7. **监控权限使用**

   通过审计日志监控敏感权限的使用情况。

常见场景
--------

场景1：普通用户
^^^^^^^^^^^^^^^

**需求**：可以创建和管理自己的文档，但不能管理其他用户或系统。

**配置**：

- 加入 ``user`` 组（基础权限）
- 在特定目录上授予读写权限（通过访问控制系统）

场景2：文档管理员
^^^^^^^^^^^^^^^^^

**需求**：可以管理所有文档，但不能管理用户。

**配置**：

创建 ``doc_admin`` 组，包含权限：

- ``super_create_document``
- ``super_list_directory``
- ``delete_document``
- ``rename_document``
- ``move``
- ``view_access_rules``
- ``set_access_rules``

场景3：系统管理员
^^^^^^^^^^^^^^^^^

**需求**：完全的系统控制权。

**配置**：

加入 ``sysop`` 组（包含所有系统权限）。

场景4：临时权限
^^^^^^^^^^^^^^^

**需求**：临时授予用户某个权限，1个月后自动撤销。

**配置**：

.. code-block:: python

   import time

   one_month_later = time.time() + 30 * 24 * 3600

   # 通过 API 或直接数据库操作
   {
       "permission": "delete_document",
       "start_time": 0,
       "end_time": one_month_later
   }

故障排除
--------

用户没有预期的权限
^^^^^^^^^^^^^^^^^^

检查清单：

1. 确认用户所属的组
2. 检查组的权限配置
3. 检查权限的生效和过期时间
4. 确认用户的直接权限
5. 查看审计日志确认权限修改历史

权限修改不生效
^^^^^^^^^^^^^^

- 确认已提交数据库更改（``session.commit()``）
- 刷新用户令牌（权限在令牌生成时计算）
- 检查是否有缓存影响

无法删除用户组
^^^^^^^^^^^^^^

- 确认组不是默认组（``user`` 或 ``sysop``）
- 检查是否有用户仍属于该组
- 确认有 ``delete_group`` 权限

相关文档
--------

- :doc:`access_control` - 访问控制系统详解
- :doc:`api_refs` - 权限相关 API 接口
- :doc:`database` - 数据库模型详解
- :doc:`audit` - 审计日志系统
