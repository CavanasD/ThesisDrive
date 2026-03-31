访问控制系统
============

CFMS 实现了一套灵活的访问控制系统，允许对文档和目录设置细粒度的访问规则。

.. contents:: 目录
   :local:
   :depth: 2

系统概述
--------

访问控制机制
^^^^^^^^^^^^

CFMS 的访问控制基于以下几个层次：

1. **系统权限** - 用户必须拥有相应的系统权限（如 ``create_document``）
2. **访问规则** - 资源可以定义访问规则，限制谁可以访问
3. **访问授权** - 可以明确授予特定用户或组对资源的访问权限
4. **继承规则** - 子目录和文档可以继承父目录的访问规则

访问类型
^^^^^^^^

CFMS 支持四种访问类型：

.. list-table::
   :header-rows: 1
   :widths: 15 60

   * - 访问类型
     - 说明
   * - read
     - 读取资源内容
   * - write
     - 修改资源内容
   * - move
     - 移动资源到其他位置
   * - manage
     - 管理资源（包括设置访问规则）

访问规则格式
------------

基本结构
^^^^^^^^

访问规则以 JSON 格式存储，基本结构如下：

.. code-block:: json

   [
       {
           "match": "any",
           "match_groups": [
               {
                   "match": "all",
                   "rights": {
                       "match": "any",
                       "require": ["create_document"]
                   },
                   "groups": {
                       "match": "any",
                       "require": ["user"]
                   }
               }
           ]
       }
   ]

规则组成
^^^^^^^^

1. **顶层数组** - 包含多个规则对象，所有规则必须同时满足（AND 关系）

2. **规则对象** - 每个对象包含：
   
   - ``match``: 匹配模式（``"all"`` 或 ``"any"``）
   - ``match_groups``: 子规则组数组

3. **子规则组** - 包含具体的权限和组要求：
   
   - ``match``: 匹配模式
   - ``rights``: 权限要求
   - ``groups``: 用户组要求

4. **权限/组要求** - 指定需要的权限或组：
   
   - ``match``: 匹配模式（``"all"`` - 全部满足，``"any"`` - 任一满足）
   - ``require``: 所需权限或组的数组

匹配逻辑
--------

匹配模式
^^^^^^^^

**all（全部匹配）**

要求数组中的所有项都必须满足：

.. code-block:: json

   {
       "match": "all",
       "require": ["permission1", "permission2"]
   }

用户必须同时拥有 ``permission1`` 和 ``permission2``。

**any（任一匹配）**

只要数组中有一项满足即可：

.. code-block:: json

   {
       "match": "any",
       "require": ["permission1", "permission2"]
   }

用户只需拥有 ``permission1`` 或 ``permission2`` 中的任意一个。

规则评估流程
^^^^^^^^^^^^

当用户请求访问资源时，系统执行以下步骤：

1. 获取资源的访问规则
2. 如果没有规则，默认允许访问（如果用户有基本系统权限）
3. 如果有规则，按顺序评估每个规则对象：
   
   - 评估规则对象中的所有子规则组
   - 根据 ``match`` 模式决定是全部满足还是任一满足
   - 检查用户的权限和组是否符合要求

4. 所有顶层规则对象都必须满足（AND 关系）
5. 检查是否有直接的访问授权记录
6. 检查父目录的继承规则（如适用）

规则示例
--------

示例 1：简单权限检查
^^^^^^^^^^^^^^^^^^^^

要求用户拥有 ``read`` 权限：

.. code-block:: json

   [
       {
           "match": "any",
           "match_groups": [
               {
                   "match": "any",
                   "rights": {
                       "match": "any",
                       "require": ["read"]
                   },
                   "groups": {
                       "match": "any",
                       "require": []
                   }
               }
           ]
       }
   ]

示例 2：用户组限制
^^^^^^^^^^^^^^^^^^

只允许 ``editors`` 组的成员访问：

.. code-block:: json

   [
       {
           "match": "any",
           "match_groups": [
               {
                   "match": "any",
                   "rights": {
                       "match": "any",
                       "require": []
                   },
                   "groups": {
                       "match": "any",
                       "require": ["editors"]
                   }
               }
           ]
       }
   ]

示例 3：组合条件
^^^^^^^^^^^^^^^^

要求用户既属于 ``editors`` 组，又拥有 ``create_document`` 权限：

.. code-block:: json

   [
       {
           "match": "any",
           "match_groups": [
               {
                   "match": "all",
                   "rights": {
                       "match": "all",
                       "require": ["create_document"]
                   },
                   "groups": {
                       "match": "all",
                       "require": ["editors"]
                   }
               }
           ]
       }
   ]

示例 4：复杂规则
^^^^^^^^^^^^^^^^

允许管理员或编辑组中有特定权限的用户：

.. code-block:: json

   [
       {
           "match": "any",
           "match_groups": [
               {
                   "match": "any",
                   "rights": {
                       "match": "any",
                       "require": []
                   },
                   "groups": {
                       "match": "any",
                       "require": ["sysop"]
                   }
               },
               {
                   "match": "all",
                   "rights": {
                       "match": "all",
                       "require": ["read", "write"]
                   },
                   "groups": {
                       "match": "all",
                       "require": ["editors"]
                   }
               }
           ]
       }
   ]

这个规则允许：

- 任何 ``sysop`` 组成员，或
- 同时满足：属于 ``editors`` 组且拥有 ``read`` 和 ``write`` 权限

访问授权
--------

ObjectAccessEntry
^^^^^^^^^^^^^^^^^

除了访问规则外，还可以通过 ``ObjectAccessEntry`` 直接授予访问权限：

.. code-block:: python

   from include.database.models.classic import ObjectAccessEntry

   entry = ObjectAccessEntry(
       object_type="documents",  # 或 "folders"
       object_id="doc123",
       subject_type="user",      # 或 "group"
       subject_name="user1",
       access_type="read"        # read, write, move, manage
   )

这种方式创建的访问权限会绕过访问规则的检查。

通过 API 授权
^^^^^^^^^^^^^

使用 ``grant_access`` API：

.. code-block:: json

   {
       "action": "grant_access",
       "data": {
           "target_type": "document",
           "target_id": "doc123",
           "subject_type": "user",
           "subject_name": "user1",
           "access_type": "read"
       },
       "username": "admin",
       "token": "your_token"
   }

继承机制
--------

父目录继承
^^^^^^^^^^

子目录和文档可以继承父目录的访问规则。继承行为由两个标志控制：

1. **父目录设置** - ``__subinherit__`` 标志
   
   - ``true`` （默认）：允许子资源继承
   - ``false``：子资源不继承此规则

2. **子资源设置** - ``__noinherit__`` 标志
   
   - 指定不继承的操作类型
   - 可以是具体操作名或 ``"all"``

继承示例
^^^^^^^^

父目录规则：

.. code-block:: json

   [
       {
           "match": "any",
           "__subinherit__": true,
           "match_groups": [...]
       }
   ]

子资源禁用继承：

.. code-block:: json

   [
       {
           "__noinherit__": ["read", "write"]
       }
   ]

这样子资源的 ``read`` 和 ``write`` 操作不会继承父目录的规则。

根目录规则
^^^^^^^^^^

根目录的继承行为由策略配置 ``permission_on_rootdir`` 中的 
``inherit_by_subdirectory`` 选项控制。

设置访问规则
------------

通过 API 设置
^^^^^^^^^^^^^

为文档设置规则：

.. code-block:: json

   {
       "action": "set_document_rules",
       "data": {
           "document_id": "doc123",
           "rules": [
               {
                   "access_type": "read",
                   "rule_data": {
                       "match": "any",
                       "match_groups": [
                           {
                               "match": "any",
                               "rights": {
                                   "match": "any",
                                   "require": ["read"]
                               },
                               "groups": {
                                   "match": "any",
                                   "require": []
                               }
                           }
                       ]
                   }
               }
           ]
       },
       "username": "admin",
       "token": "your_token"
   }

为目录设置规则：

使用 ``set_directory_rules``，格式相同但使用 ``folder_id``。

通过数据库设置
^^^^^^^^^^^^^^

.. code-block:: python

   from include.database.models.entity import DocumentAccessRule
   from include.database.handler import Session

   with Session() as session:
       rule = DocumentAccessRule(
           document_id="doc123",
           access_type="read",
           rule_data={
               "match": "any",
               "match_groups": [...]
           }
       )
       session.add(rule)
       session.commit()

查看访问规则
------------

获取文档规则
^^^^^^^^^^^^

.. code-block:: json

   {
       "action": "get_document_access_rules",
       "data": {
           "document_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

获取目录规则
^^^^^^^^^^^^

.. code-block:: json

   {
       "action": "get_directory_access_rules",
       "data": {
           "folder_id": "folder123"
       },
       "username": "admin",
       "token": "your_token"
   }

查看访问授权
^^^^^^^^^^^^

.. code-block:: json

   {
       "action": "view_access_entries",
       "data": {
           "target_type": "document",
           "target_id": "doc123"
       },
       "username": "admin",
       "token": "your_token"
   }

最佳实践
--------

1. **默认拒绝策略**
   
   对敏感资源，明确设置访问规则而不是依赖默认行为。

2. **使用用户组**
   
   在规则中使用用户组而不是单个用户，便于管理。

3. **分层设计**
   
   利用继承机制，在父目录设置通用规则，在子资源设置特殊规则。

4. **简化规则**
   
   保持规则简单明了，复杂规则难以理解和维护。

5. **文档化**
   
   记录每个规则的用途和业务逻辑。

6. **定期审查**
   
   定期检查访问规则，移除过时的规则。

7. **测试规则**
   
   修改规则后，测试各种用户的访问权限是否符合预期。

故障排除
--------

用户无法访问资源
^^^^^^^^^^^^^^^^

检查清单：

1. 用户是否有相应的系统权限
2. 资源是否有访问规则限制
3. 用户的权限和组是否满足规则要求
4. 是否有直接的访问授权
5. 检查父目录的继承规则
6. 查看审计日志了解拒绝原因

规则不生效
^^^^^^^^^^

- 确认规则格式正确（JSON 有效）
- 检查 ``match`` 字段的值（``"all"`` 或 ``"any"``）
- 验证权限和组名称的拼写
- 确认规则已保存到数据库

继承问题
^^^^^^^^

- 检查父目录的 ``__subinherit__`` 设置
- 检查子资源的 ``__noinherit__`` 设置
- 确认资源的 ``folder_id`` 正确指向父目录

相关文档
--------

- :doc:`groups_and_rights` - 权限与用户组系统
- :doc:`api_refs` - 访问控制相关 API
- :doc:`database` - 访问控制数据模型
