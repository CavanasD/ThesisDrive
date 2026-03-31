审计日志
========

CFMS 记录所有重要操作的审计日志，用于安全审计和故障排查。

.. contents:: 目录
   :local:
   :depth: 2

审计系统概述
------------

日志记录内容
^^^^^^^^^^^^

审计日志记录以下信息：

- **操作类型**（action）：执行的操作，如 ``login``, ``delete_document``
- **操作用户**（username）：执行操作的用户
- **操作结果**（result）：HTTP 风格的状态码
- **操作目标**（target）：操作的目标对象（可选）
- **附加数据**（data）：操作的详细信息（可选）
- **客户端地址**（remote_address）：客户端 IP 地址
- **时间戳**（timestamp）：操作发生的时间

记录的操作
^^^^^^^^^^

所有 API 操作都会被记录，包括：

- 认证操作（登录、令牌刷新）
- 文档操作（创建、删除、修改）
- 目录操作（创建、删除、修改）
- 用户管理（创建、删除、修改用户）
- 权限管理（修改权限、用户组）
- 系统管理（锁定、关闭）

数据库结构
----------

audit_entries 表
^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 15 50

   * - 字段
     - 类型
     - 说明
   * - id
     - INTEGER
     - 主键，自动递增
   * - action
     - VARCHAR(255)
     - 操作类型
   * - username
     - VARCHAR(255)
     - 操作用户（外键到 users 表）
   * - result
     - INTEGER
     - 操作结果状态码
   * - target
     - VARCHAR(255)
     - 操作目标（可选）
   * - data
     - JSON
     - 附加数据（可选）
   * - remote_address
     - VARCHAR(255)
     - 客户端 IP 地址
   * - timestamp
     - FLOAT
     - Unix 时间戳

记录日志
--------

使用 log_audit 函数
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   from include.util.audit import log_audit

   # 基本用法
   log_audit("login", 200)

   # 包含目标
   log_audit("delete_document", 200, target="doc123")

   # 包含用户和数据
   log_audit(
       "create_user",
       200,
       target="newuser",
       data={"groups": ["user"]},
       username="admin",
       remote_address="192.168.1.100"
   )

在请求处理器中
^^^^^^^^^^^^^^

请求处理器自动记录日志：

.. code-block:: python

   class RequestHandler:
       def handle(self, handler: ConnectionHandler):
           # 执行操作
           
           # 返回审计信息
           return (
               200,              # 结果状态码
               "doc123",         # 目标
               {"size": 1024},   # 附加数据（可选）
               "admin"           # 用户名（可选）
           )

连接处理器会自动调用 ``log_audit``。

查看日志
--------

通过 API 查看
^^^^^^^^^^^^^

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

响应示例：

.. code-block:: json

   {
       "code": 200,
       "message": "Audit logs retrieved successfully",
       "data": {
           "logs": [
               {
                   "id": 1,
                   "action": "login",
                   "username": "admin",
                   "result": 200,
                   "target": "admin",
                   "remote_address": "127.0.0.1",
                   "timestamp": 1699999999.0
               },
               {
                   "id": 2,
                   "action": "create_document",
                   "username": "admin",
                   "result": 200,
                   "target": "doc123",
                   "data": {"folder_id": "root"},
                   "remote_address": "127.0.0.1",
                   "timestamp": 1700000000.0
               }
           ],
           "total": 1000
       }
   }

分页参数
^^^^^^^^

- ``limit``：每页返回的记录数（默认 100）
- ``offset``：跳过的记录数（默认 0）

示例：

- 第 1 页：``limit=100, offset=0``
- 第 2 页：``limit=100, offset=100``
- 第 3 页：``limit=100, offset=200``

直接查询数据库
^^^^^^^^^^^^^^

.. code-block:: python

   from include.database.handler import Session
   from include.database.models.classic import AuditEntry

   with Session() as session:
       # 查询最近的 100 条日志
       logs = session.query(AuditEntry)\
           .order_by(AuditEntry.timestamp.desc())\
           .limit(100)\
           .all()
       
       for log in logs:
           print(f"{log.timestamp}: {log.username} {log.action} {log.result}")

日志分析
--------

失败的登录尝试
^^^^^^^^^^^^^^

.. code-block:: python

   from include.database.handler import Session
   from include.database.models.classic import AuditEntry

   with Session() as session:
       failed_logins = session.query(AuditEntry)\
           .filter(AuditEntry.action == "login")\
           .filter(AuditEntry.result == 401)\
           .order_by(AuditEntry.timestamp.desc())\
           .limit(100)\
           .all()
       
       # 按 IP 地址统计
       from collections import Counter
       ip_counter = Counter(log.remote_address for log in failed_logins)
       print(ip_counter.most_common(10))

用户活动统计
^^^^^^^^^^^^

.. code-block:: python

   # 统计用户操作次数
   user_actions = session.query(AuditEntry.username, func.count())\
       .group_by(AuditEntry.username)\
       .order_by(func.count().desc())\
       .all()

操作类型分布
^^^^^^^^^^^^

.. code-block:: python

   # 统计各类操作的次数
   action_stats = session.query(AuditEntry.action, func.count())\
       .group_by(AuditEntry.action)\
       .order_by(func.count().desc())\
       .all()

错误率分析
^^^^^^^^^^

.. code-block:: python

   # 统计各种错误
   import time

   # 最近 24 小时
   yesterday = time.time() - 86400

   errors = session.query(AuditEntry)\
       .filter(AuditEntry.timestamp >= yesterday)\
       .filter(AuditEntry.result >= 400)\
       .all()

   # 按错误类型分组
   error_by_code = {}
   for log in errors:
       code = log.result
       if code not in error_by_code:
           error_by_code[code] = []
       error_by_code[code].append(log)

时间序列分析
^^^^^^^^^^^^

.. code-block:: python

   import matplotlib.pyplot as plt
   from datetime import datetime

   # 按小时统计操作数
   hour_counts = {}
   for log in logs:
       hour = datetime.fromtimestamp(log.timestamp).hour
       hour_counts[hour] = hour_counts.get(hour, 0) + 1

   # 绘制图表
   plt.bar(hour_counts.keys(), hour_counts.values())
   plt.xlabel('Hour')
   plt.ylabel('Operations')
   plt.title('Operations by Hour')
   plt.show()

日志导出
--------

导出为 CSV
^^^^^^^^^^

.. code-block:: python

   import csv

   with Session() as session:
       logs = session.query(AuditEntry).all()
       
       with open('audit_logs.csv', 'w', newline='') as f:
           writer = csv.writer(f)
           writer.writerow(['ID', 'Timestamp', 'Username', 'Action', 
                           'Result', 'Target', 'IP'])
           
           for log in logs:
               writer.writerow([
                   log.id,
                   log.timestamp,
                   log.username,
                   log.action,
                   log.result,
                   log.target,
                   log.remote_address
               ])

导出为 JSON
^^^^^^^^^^^

.. code-block:: python

   import json

   with Session() as session:
       logs = session.query(AuditEntry).all()
       
       log_dicts = [
           {
               "id": log.id,
               "timestamp": log.timestamp,
               "username": log.username,
               "action": log.action,
               "result": log.result,
               "target": log.target,
               "data": log.data,
               "remote_address": log.remote_address
           }
           for log in logs
       ]
       
       with open('audit_logs.json', 'w') as f:
           json.dump(log_dicts, f, indent=2)

日志维护
--------

清理旧日志
^^^^^^^^^^

.. code-block:: python

   import time

   # 删除 90 天前的日志
   cutoff = time.time() - 90 * 86400

   with Session() as session:
       deleted = session.query(AuditEntry)\
           .filter(AuditEntry.timestamp < cutoff)\
           .delete()
       session.commit()
       
       print(f"Deleted {deleted} old log entries")

归档日志
^^^^^^^^

.. code-block:: python

   # 导出旧日志到文件后删除
   import json

   cutoff = time.time() - 90 * 86400

   with Session() as session:
       old_logs = session.query(AuditEntry)\
           .filter(AuditEntry.timestamp < cutoff)\
           .all()
       
       # 导出
       if old_logs:
           with open(f'archived_logs_{cutoff}.json', 'w') as f:
               json.dump([log.to_dict() for log in old_logs], f)
           
           # 删除
           for log in old_logs:
               session.delete(log)
           session.commit()

定期维护任务
^^^^^^^^^^^^

可以使用 cron 或类似工具定期执行维护：

.. code-block:: bash

   # /etc/cron.daily/cfms-audit-cleanup
   #!/bin/bash
   cd /path/to/cfms
   python -c "from scripts import cleanup_audit_logs; cleanup_audit_logs()"

监控和告警
----------

异常检测
^^^^^^^^

设置告警规则：

1. **短时间内大量失败登录**

.. code-block:: python

   recent_failures = count_failed_logins(last_minutes=10)
   if recent_failures > 50:
       send_alert("Possible brute force attack")

2. **权限提升操作**

.. code-block:: python

   if log.action in ['change_user_groups', 'set_group_permissions']:
       if log.username not in TRUSTED_ADMINS:
           send_alert(f"Permission change by {log.username}")

3. **批量删除**

.. code-block:: python

   recent_deletes = count_actions('delete_document', last_minutes=5)
   if recent_deletes > 100:
       send_alert("Massive deletion detected")

集成监控系统
^^^^^^^^^^^^

可以将日志发送到监控系统（如 ELK, Prometheus, Grafana）。

最佳实践
--------

1. **定期审查**

   - 每周检查审计日志
   - 关注异常模式
   - 分析失败操作

2. **保留策略**

   - 至少保留 90 天日志
   - 重要日志永久归档
   - 定期清理旧日志

3. **访问控制**

   - 限制审计日志的访问
   - 仅授予必要人员 ``view_audit_logs`` 权限
   - 记录谁查看了审计日志

4. **数据完整性**

   - 定期备份日志
   - 防止日志被篡改
   - 考虑使用只读副本

5. **性能优化**

   - 为常用查询字段添加索引
   - 定期清理旧日志
   - 考虑将日志存储在独立数据库

故障排除
--------

日志丢失
^^^^^^^^

检查：

- 数据库连接是否正常
- 磁盘空间是否充足
- 是否有错误日志

日志过多
^^^^^^^^

- 检查是否有异常的操作循环
- 考虑增加日志级别
- 实施日志清理策略

查询慢
^^^^^^

- 为 ``timestamp`` 字段添加索引
- 限制查询的时间范围
- 使用分页

相关文档
--------

- :doc:`security` - 安全特性
- :doc:`api_refs` - ``view_audit_logs`` API
- :doc:`database` - ``audit_entries`` 表结构
