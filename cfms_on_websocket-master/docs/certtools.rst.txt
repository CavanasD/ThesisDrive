证书工具（certtools）
======================

``certtools`` 是 CFMS 项目的配套证书管理工具集，用于生成和管理 SSL/TLS 证书链。该工具集位于 cfms_on_websocket 代码库的 ``certtools/`` 子模块中，独立维护于 `creeper19472/cfms_certtools <https://github.com/creeper19472/cfms_certtools>`_ 仓库。

.. contents:: 目录
   :local:
   :depth: 2

简介
----

certtools 提供了一套 Python 脚本，用于创建完整的证书颁发机构（CA）层次结构：

- **根证书颁发机构（Root CA）** - 信任链的顶端
- **中间证书颁发机构（Intermediate CA）** - 由根 CA 签发
- **终端实体证书（End Entity / EE）** - 由中间 CA 签发，用于实际的服务器

这种三层结构符合 PKI 最佳实践，提供了灵活性和安全性的平衡。

核心工具
--------

generate_ca.py - 生成根 CA
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**功能说明**

生成根证书颁发机构（Root CA）的私钥和证书。根 CA 是整个证书信任链的起点。

**证书特性**

- **算法**：ECC（椭圆曲线加密）SECP256R1 曲线
- **哈希算法**：SHA-256
- **有效期**：约 10 年（3650 天）
- **基本约束**：CA=TRUE，path_length=None（无限制）
- **密钥用途**：
  
  - 数字签名
  - 证书签名
  - CRL 签名

**证书主题**

.. code-block:: text

   C=CN
   ST=Beijing
   L=Beijing
   O=CFMS Management Organization
   CN=CFMS Validation Root CA

**使用方法**

.. code-block:: console

   $ cd cfms_on_websocket/certtools
   $ mkdir -p signing
   $ python generate_ca.py

**输出文件**

- ``signing/root_key.pem`` - 根 CA 私钥（未加密）
- ``signing/root_cert.pem`` - 根 CA 证书

.. warning::

   根 CA 私钥是整个 PKI 体系的核心，必须妥善保管。建议：
   
   - 使用密码保护私钥（修改脚本中的 ``encryption_algorithm``）
   - 将私钥存储在安全的离线位置
   - 仅在需要签发中间 CA 证书时使用

generate_intermediate.py - 生成中间 CA
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**功能说明**

生成中间证书颁发机构（Intermediate CA）的私钥和证书，由根 CA 签发。中间 CA 用于签发终端实体证书。

**证书特性**

- **算法**：ECC SECP256R1 曲线
- **哈希算法**：SHA-256
- **有效期**：约 3 年（1095 天）
- **基本约束**：CA=TRUE，path_length=0（不能再签发下级 CA）
- **密钥用途**：
  
  - 数字签名
  - 证书签名
  - CRL 签名

**证书主题**

.. code-block:: text

   C=CN
   ST=Beijing
   L=Beijing
   O=CFMS Intermediate CA Management Organization
   CN=CFMS Intermediate CA

**前置要求**

运行此脚本前，需要先生成根 CA：

- ``signing/root_cert.pem``
- ``signing/root_key.pem``

**使用方法**

.. code-block:: console

   $ cd cfms_on_websocket/certtools
   $ python generate_intermediate.py

**输出文件**

- ``signing/int_key.pem`` - 中间 CA 私钥（未加密）
- ``signing/int_cert.pem`` - 中间 CA 证书

.. note::

   中间 CA 的 path_length=0 限制意味着它不能再签发下级 CA 证书，只能签发终端实体证书。这是一种常见的安全实践。

generate_ee.py - 生成终端实体证书
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**功能说明**

生成终端实体（End Entity）证书，用于实际的服务器或客户端。支持多个域名（SAN）。

**证书特性**

- **算法**：ECC SECP256R1 曲线
- **哈希算法**：SHA-256
- **有效期**：可配置（默认 30 天）
- **基本约束**：CA=FALSE
- **密钥用途**：
  
  - 数字签名
  - 密钥加密
  - CRL 签名

- **扩展密钥用途**：
  
  - 服务器认证（TLS Web Server Authentication）
  - 客户端认证（TLS Web Client Authentication）

- **主题备用名称（SAN）**：支持多个域名

**证书主题**

.. code-block:: text

   C=CN
   ST=Beijing
   L=Beijing
   O=CFMS End Entity Organization

**前置要求**

运行此脚本前，需要将中间 CA 证书和私钥复制到当前目录：

.. code-block:: console

   $ cp signing/int_cert.pem ./
   $ cp signing/int_key.pem ./

**使用方法**

基本用法（生成 30 天有效期的证书）：

.. code-block:: console

   $ python generate_ee.py example.com

支持多个域名：

.. code-block:: console

   $ python generate_ee.py example.com www.example.com api.example.com

指定有效期（例如 365 天）：

.. code-block:: console

   $ python generate_ee.py example.com -D 365

**命令行参数**

- ``domains`` - 一个或多个域名（必需）
- ``-D, --days`` - 证书有效期（天数），默认 30

**输出文件**

- ``ee_key.pem`` - 终端实体私钥（未加密）
- ``ee_cert.pem`` - 终端实体证书

**使用示例**

为 CFMS 服务器生成证书：

.. code-block:: console

   $ python generate_ee.py localhost 127.0.0.1 your-server-domain.com -D 365

.. note::

   生成的终端实体证书需要与中间 CA 证书和根 CA 证书组成完整的证书链，才能被客户端正确验证。

pem2der.py - PEM 转 DER 格式
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**功能说明**

将 PEM 格式的 X.509 证书转换为 DER 格式。某些应用程序和系统需要 DER 格式的证书。

**使用方法**

.. code-block:: console

   $ python pem2der.py <pem_file_path>

**示例**

.. code-block:: console

   $ python pem2der.py ee_cert.pem
   DER file saved to: ee_cert.der

**输出**

生成与输入文件同名但扩展名为 ``.der`` 的文件。

完整工作流程
------------

以下是使用 certtools 创建完整证书链的推荐步骤：

1. 生成根 CA
^^^^^^^^^^^^

.. code-block:: console

   $ cd cfms_on_websocket/certtools
   $ mkdir -p signing
   $ python generate_ca.py

此步骤会生成：

- ``signing/root_key.pem``
- ``signing/root_cert.pem``

.. important::

   根 CA 私钥应在生成后立即备份到安全位置，并考虑从在线系统中移除。

2. 生成中间 CA
^^^^^^^^^^^^^^

.. code-block:: console

   $ python generate_intermediate.py

此步骤会生成：

- ``signing/int_key.pem``
- ``signing/int_cert.pem``

3. 准备签发终端证书
^^^^^^^^^^^^^^^^^^^

将中间 CA 文件复制到工作目录：

.. code-block:: console

   $ cp signing/int_cert.pem ./
   $ cp signing/int_key.pem ./

4. 生成服务器证书
^^^^^^^^^^^^^^^^^

为您的 CFMS 服务器生成证书：

.. code-block:: console

   $ python generate_ee.py localhost 127.0.0.1 your-domain.com -D 365

此步骤会生成：

- ``ee_key.pem`` - 服务器私钥
- ``ee_cert.pem`` - 服务器证书

5. 创建证书链
^^^^^^^^^^^^^

将证书组合成完整的证书链文件：

.. code-block:: console

   $ cat ee_cert.pem int_cert.pem > fullchain.pem

.. note::

   对于 TLS 服务器，通常只需要包含终端实体证书和中间 CA 证书。根 CA 证书应该已经在客户端的信任存储中，不需要在证书链中传输。包含根证书会不必要地增加证书链大小。

如果需要完整的证书链（例如用于某些测试场景），可以包含根证书：

.. code-block:: console

   $ cat ee_cert.pem int_cert.pem root_cert.pem > fullchain_with_root.pem

6. 部署到 CFMS
^^^^^^^^^^^^^^

将证书文件复制到 CFMS 服务器目录：

.. code-block:: console

   $ cp ee_key.pem ../content/ssl/server_key.pem
   $ cp fullchain.pem ../content/ssl/server_cert.pem

或者在 ``config.toml`` 中指定证书路径：

.. code-block:: toml

   [server]
   ssl_keyfile = "/path/to/ee_key.pem"
   ssl_certfile = "/path/to/fullchain.pem"

证书验证
--------

生成证书后，可以使用 OpenSSL 工具验证证书：

验证证书链
^^^^^^^^^^

.. code-block:: console

   $ openssl verify -CAfile root_cert.pem -untrusted int_cert.pem ee_cert.pem

成功输出：

.. code-block:: text

   ee_cert.pem: OK

查看证书内容
^^^^^^^^^^^^

查看根 CA 证书：

.. code-block:: console

   $ openssl x509 -in root_cert.pem -text -noout

查看中间 CA 证书：

.. code-block:: console

   $ openssl x509 -in int_cert.pem -text -noout

查看终端实体证书：

.. code-block:: console

   $ openssl x509 -in ee_cert.pem -text -noout

验证证书链完整性：

.. code-block:: console

   $ openssl verify -CAfile <(cat root_cert.pem int_cert.pem) ee_cert.pem

安全最佳实践
------------

私钥保护
^^^^^^^^

1. **根 CA 私钥**
   
   - 应使用强密码加密（修改脚本使用 ``BestAvailableEncryption``）
   - 存储在离线、安全的位置（如 USB 设备或硬件安全模块）
   - 仅在签发中间 CA 时使用
   - 考虑使用多人授权机制

2. **中间 CA 私钥**
   
   - 应使用密码保护
   - 限制访问权限（Unix: ``chmod 600``）
   - 定期备份
   - 在安全的服务器上使用

3. **终端实体私钥**
   
   - 不应在不安全的网络上传输
   - 服务器文件权限应严格限制
   - 考虑使用硬件安全模块（HSM）

证书有效期
^^^^^^^^^^

推荐的证书有效期：

- **根 CA**：10 年（当前默认）
- **中间 CA**：3-5 年（当前 3 年）
- **终端实体**：90 天到 1 年（推荐 90 天）

.. note::

   较短的证书有效期可以提高安全性，但需要更频繁的更新。使用自动化工具（如 ACME 协议）可以简化短期证书的管理。

证书吊销
^^^^^^^^

虽然当前 certtools 不直接支持 CRL（证书吊销列表）或 OCSP（在线证书状态协议），但：

- 证书已启用 CRL 签名密钥用途
- 可以手动生成和维护 CRL
- 考虑实现 OCSP 响应器以支持实时证书状态查询

备份策略
^^^^^^^^

关键文件的备份清单：

.. code-block:: text

   signing/
   ├── root_key.pem      ← 最高优先级，离线存储
   ├── root_cert.pem     ← 公开可用，但应备份
   ├── int_key.pem       ← 高优先级
   └── int_cert.pem      ← 公开可用，但应备份

建议：

- 使用加密备份介质
- 多地异地备份
- 定期测试恢复流程
- 记录备份和恢复程序

技术细节
--------

ECC vs RSA
^^^^^^^^^^

certtools 使用 ECC（椭圆曲线加密）而非传统的 RSA，原因包括：

**优势**

- **更短的密钥长度**：256 位 ECC ≈ 3072 位 RSA
- **更快的性能**：签名和验证速度更快
- **更小的证书**：减少网络传输开销
- **更低的计算需求**：适合资源受限的环境

**曲线选择**

使用 **SECP256R1** （也称为 P-256 或 prime256v1）：

- NIST 标准曲线
- 广泛支持
- 256 位密钥长度
- 安全等级约 128 位

证书扩展
^^^^^^^^

certtools 生成的证书包含以下关键扩展：

**基本约束（Basic Constraints）**

- CA 证书：``CA:TRUE``
- 中间 CA：``pathlen:0`` （限制证书链深度）
- 终端实体：``CA:FALSE``

**密钥用途（Key Usage）**

根据证书类型设置适当的密钥用途标志，符合 RFC 5280 规范。

**主题密钥标识符（Subject Key Identifier）**

从公钥自动生成，用于唯一标识证书。

**颁发者密钥标识符（Authority Key Identifier）**

链接到签发者的主题密钥标识符，构建证书链。

**主题备用名称（Subject Alternative Name）**

终端实体证书支持多个域名，这是现代 TLS 的标准要求。

依赖项
------

certtools 需要以下 Python 库：

.. code-block:: text

   cryptography

安装依赖：

.. code-block:: console

   $ pip install cryptography

``cryptography`` 库版本要求：

- 推荐：最新稳定版本
- 最低：支持 ECC 和 X.509 证书生成的版本

故障排除
--------

找不到签名文件
^^^^^^^^^^^^^^

**错误信息**：

.. code-block:: text

   FileNotFoundError: [Errno 2] No such file or directory: './signing/root_cert.pem'

**解决方法**：

确保按照正确的顺序运行脚本，并且 ``signing/`` 目录存在：

.. code-block:: console

   $ mkdir -p signing
   $ python generate_ca.py
   $ python generate_intermediate.py

证书验证失败
^^^^^^^^^^^^

**错误信息**：

.. code-block:: text

   error 20 at 0 depth lookup: unable to get local issuer certificate

**可能原因**：

1. 证书链不完整
2. 证书顺序错误
3. 使用了错误的 CA 证书

**解决方法**：

确保证书链的顺序正确：终端实体 → 中间 CA → 根 CA

.. code-block:: console

   $ cat ee_cert.pem int_cert.pem root_cert.pem > fullchain.pem

浏览器不信任证书
^^^^^^^^^^^^^^^^

**原因**：

自签名根 CA 不在浏览器或系统的信任存储中。

**解决方法**：

1. **开发环境**：在浏览器中手动添加根 CA 证书到信任列表
2. **生产环境**：使用受信任的 CA（如 Let's Encrypt）签发证书

导入根 CA 到系统信任存储：

**Linux (Ubuntu/Debian)**：

.. code-block:: console

   $ sudo cp root_cert.pem /usr/local/share/ca-certificates/cfms_root.crt
   $ sudo update-ca-certificates

**macOS**：

.. code-block:: console

   $ sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain root_cert.pem

**Windows**：

使用证书管理器（certmgr.msc）导入到"受信任的根证书颁发机构"。

未来改进
--------

certtools 的潜在改进方向：

配置文件支持
^^^^^^^^^^^^

使用配置文件（YAML/TOML）指定证书参数，而不是硬编码：

.. code-block:: yaml

   root_ca:
     common_name: "CFMS Validation Root CA"
     organization: "CFMS Management Organization"
     validity_days: 3650
     key_algorithm: "ECC"
     curve: "SECP256R1"

交互式模式
^^^^^^^^^^

添加命令行界面，引导用户完成证书生成过程：

.. code-block:: console

   $ python certtools.py --interactive

自动化脚本
^^^^^^^^^^

一键生成完整证书链的脚本：

.. code-block:: console

   $ python setup_pki.py --domains example.com www.example.com

CRL 和 OCSP 支持
^^^^^^^^^^^^^^^^^

实现证书吊销功能：

- 生成和维护 CRL
- OCSP 响应器实现
- 自动更新机制

硬件安全模块（HSM）集成
^^^^^^^^^^^^^^^^^^^^^^^^

支持将私钥存储在硬件安全模块中，提高安全性。

ACME 协议支持
^^^^^^^^^^^^^

实现 ACME 客户端，支持自动化证书申请和更新。

相关资源
--------

- **RFC 5280** - Internet X.509 Public Key Infrastructure Certificate and CRL Profile
- **RFC 6960** - X.509 Internet Public Key Infrastructure Online Certificate Status Protocol - OCSP
- **cryptography 文档** - https://cryptography.io/

参见
----

- :doc:`setup` - CFMS 服务器安装，包含 SSL 证书配置
- :doc:`security` - 安全特性，包含 TLS/SSL 详细说明
- :doc:`config` - 配置文件，包含 SSL 相关配置项
