.. _installation:

安装与配置
============

系统要求
--------

CFMS 服务端仅支持在 Python 3.13 及更高版本运行。尽管理论上服务端不存在平台
特异的实现，但我们仅在 Windows 和 Linux 上进行了测试，因此不确定 macOS 的
兼容性如何。

无需额外配置，CFMS 服务端就可依赖 SQLite 数据库而运作。不过为了更好的性能和
可扩展性，建议在条件允许时换用其他功能更为强大的数据库引擎。

快速开始
--------

1. 克隆代码仓库
^^^^^^^^^^^^^^^

从 GitHub 克隆 CFMS 服务端仓库：

.. code-block:: console

   $ git clone https://github.com/creeper19472/cfms_on_websocket.git
   $ cd cfms_on_websocket/src

2. 安装依赖
^^^^^^^^^^^^^^^

建议使用虚拟环境来隔离依赖。如果你正使用 pip 来进行包管理，事先运行

.. code-block:: console
   
   $ python -m venv .venv

来创建一个虚拟环境，然后通过运行 ``source .venv/bin/activate`` （对于 
Linux / macOS） 或 ``.venv/Scripts/activate`` （对于 Windows）激活它。

.. note::
   建议使用 uv 来管理 Python 版本和依赖。uv 是一个现代的 Python 包管
   理工具，提供了更快的安装速度和更好的依赖解析能力。

   另外，它所使用的 Python 分发版还携带了较新的 OpenSSL 构建，能够提供对
   后量子加密算法的支持。现在，当 OpenSSL 版本过低（<3.5）时，服务端将在
   控制台打印一条警告。

.. tabs::

   .. tab:: uv

      .. code-block:: console

         $ uv venv
         $ uv sync --upgrade

   .. tab:: pip

      .. code-block:: console

         $ pip install .

3. 配置服务器
^^^^^^^^^^^^^

在首次启动前，需要创建配置文件 ``config.toml``。可以从示例配置开始：

.. code-block:: console

   $ cp config.sample.toml config.toml
   $ nano config.toml  # 或使用您喜欢的编辑器

详细配置说明请参见 :doc:`config` 章节。

4. 启动服务器
^^^^^^^^^^^^^

配置完成后，启动 CFMS 服务器：

.. code-block:: console

   $ python main.py

服务器启动后，您应该看到类似以下的输出：

.. code-block:: text

   [INFO] Initializating CFMS WebSocket server...
   [INFO] CFMS Core Version: 0.1.0.250919_alpha
   [INFO] CFMS WebSocket server started at wss://localhost:5104

服务器将创建名为 ``admin`` 的默认管理员账户，并将随机生成的密码保存在 ``admin_password.txt`` 文件中。请务必妥善保管该文件，并在首次登录后立即修改管理员密码。

.. note::
   建议另外创建新的管理员账户，并删除旧有的默认管理员账户，以防止对默认账户和口令的暴力攻击。

5. 验证安装
^^^^^^^^^^^

可以使用简单的 Python 脚本测试连接：

.. code-block:: python

   import asyncio
   import websockets
   import ssl
   import json

   async def test_connection():
       ssl_context = ssl.create_default_context()
       ssl_context.check_hostname = False
       ssl_context.verify_mode = ssl.CERT_NONE
       
       async with websockets.connect('wss://localhost:5104', ssl=ssl_context) as ws:
           # 请求服务器信息
           await ws.send(json.dumps({
               "action": "server_info",
               "data": {},
               "username": "",
               "token": ""
           }))
           response = await ws.recv()
           print(json.loads(response))

   asyncio.run(test_connection())

安全最佳实践
------------

1. **更改管理员密码**

   首次登录后立即修改管理员密码：

   .. code-block:: json

      {
        "action": "set_passwd",
        "data": {
          "username": "admin",
          "old_password": "<从文件读取的密码>",
          "new_password": "<您的新密码>"
        },
        "username": "admin",
        "token": "<您的令牌>"
      }

2. **配置防火墙**

   限制对服务器端口的访问，仅允许受信任的 IP 地址连接。

3. **使用有效的 SSL 证书**

   在生产环境中，应替换自签名证书为受信任的 CA 颁发的证书：

   .. code-block:: toml

      [server]
      ssl_keyfile = "/path/to/your/key.pem"
      ssl_certfile = "/path/to/your/cert.pem"

   不过，对于可能的应用场景，我们也提供了创建自签名证书的工具，详见 :doc:`certtools` 章节。

4. **设置强密码策略**

   .. caution::
      ``passwd_must_contain`` 的实现方式仍在改动之中，因此不建议使用此功能。

   在配置文件中启用密码要求：

   .. code-block:: toml

      [security]
      passwd_min_length = 12
      passwd_must_contain = [] # TODO

5. **定期备份数据库**

   定期备份 ``app.db`` 文件（SQLite）或 MySQL 数据库等。

故障排除
--------

端口已被占用
^^^^^^^^^^^^

如果看到 "Address already in use" 错误，检查端口是否被占用：

.. code-block:: console

   $ lsof -i :5104  # Linux/macOS
   $ netstat -ano | findstr :5104  # Windows

可以在 ``config.toml`` 中修改端口号。

SSL 证书错误
^^^^^^^^^^^^

如果遇到 SSL 相关错误，确保：

- ``content/ssl/`` 目录存在且有写入权限
- 首次启动时自动生成的证书文件完整

下一步
------

成功安装并启动服务器后，您可以：

- 阅读 :doc:`api` 了解如何与服务器通信
- 查看 :doc:`api_refs` 了解所有可用的 API 接口
- 学习 :doc:`groups_and_rights` 了解权限系统
- 探索 :doc:`access_control` 了解访问控制机制
- 使用 :doc:`certtools` 生成自定义 SSL 证书
