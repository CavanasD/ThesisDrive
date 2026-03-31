"""
Main entry point for initializing and testing the CFMS WebSocket application.
- Checks for the existence of an initialization file ("./init") to determine if the database needs to be set up.
- If not initialized:
    - Creates all database tables using SQLAlchemy's metadata.
    - Creates a default "sysop" user group with "shutdown" permission.
    - Adds an "admin" user with the "sysop" group.
    - Writes an "init" file to indicate initialization is complete.
- After initialization (or if already initialized):
    - Opens a database session and queries for the user with ID 1.
    - If the user exists, prints the username and all permissions.
Modules imported:
- os: For file existence checks.
- include.conf_loader.global_config: Loads global configuration.
- include.database.handler: Provides SQLAlchemy engine, Base, and Session.
- include.classes.version.Version: Handles versioning.
- include.database.models: Contains ORM models for User and UserGroup.
- include.util.user.create_user: Function to create a new user.
Constants:
- CORE_VERSION: The current version of the core application.
"""

import os

from include.classes.enum.permissions import Permissions
from include.util.entrance import global_process_request

# fix
os.makedirs("./content/logs/", exist_ok=True)
os.makedirs("./content/ssl/", exist_ok=True)

import socket
import ssl

from websockets.sync.server import serve

from include.conf_loader import global_config
from include.connection_handler import handle_connection
from include.constants import CORE_VERSION
from include.constants import DEFAULT_SSL_CERT_VALIDITY_DAYS
from include.constants import ROOT_DIRECTORY_ID
from include.database.handler import Base
from include.database.handler import Session
from include.database.handler import engine
from include.database.models.entity import Document, DocumentRevision, Folder
from include.database.models.file import File
from include.util.log import getCustomLogger
from include.util.rule.applying import set_access_rules
from include.classes.misc.guard import LoginGuard


def ensure_root_folder():
    """
    Ensure the root directory's sentinel Folder record exists in the database.
    This record carries no children of its own; it exists solely so that
    access rules (and ObjectAccessEntries) can be attached to the root directory
    through the normal access-control machinery.

    On creation the root folder is configured with default access rules that
    restrict read, write and manage access to the ``sysop`` group only.
    """
    _sysop_rule = {
        "match": "all",
        "match_groups": [
            {
                "match": "all",
                "groups": {"match": "all", "require": ["sysop"]},
            }
        ],
    }
    _DEFAULT_ROOT_ACCESS_RULES = {
        "read": [],
        "write": [_sysop_rule],
        "manage": [_sysop_rule],
    }

    with Session() as session:
        if not session.get(Folder, ROOT_DIRECTORY_ID):
            root = Folder(id=ROOT_DIRECTORY_ID, name="/")
            session.add(root)
            set_access_rules(root, _DEFAULT_ROOT_ACCESS_RULES, inherit_parent=False)
            session.commit()


def server_init():
    """
    Initializes the server by checking if the database is already set up.
    If not, it creates the necessary tables and a default admin user.
    """
    if os.path.exists("./app.db"):
        os.remove("./app.db")
    if os.path.exists("./ssl_cert.pem"):
        os.remove("./ssl_cert.pem")
    if os.path.exists("./ssl_key.pem"):
        os.remove("./ssl_key.pem")

    # Create database tables before inserting data
    Base.metadata.create_all(engine)

    from include.util.group import create_group

    create_group(
        group_name="user",
        permissions=[
            {"permission": Permissions.SET_PASSWD},
        ],
    )
    create_group(
        group_name="sysop",
        permissions=[
            {"permission": Permissions.MOVE},
            {"permission": Permissions.SHUTDOWN},
            {"permission": Permissions.SUPER_CREATE_DOCUMENT},
            {"permission": Permissions.SUPER_CREATE_DIRECTORY},
            {"permission": Permissions.SUPER_LIST_DIRECTORY},
            {"permission": Permissions.CREATE_DOCUMENT},
            {"permission": Permissions.CREATE_DIRECTORY},
            {"permission": Permissions.DELETE_DOCUMENT},
            {"permission": Permissions.RENAME_DOCUMENT},
            {"permission": Permissions.DELETE_DIRECTORY},
            {"permission": Permissions.RENAME_DIRECTORY},
            {"permission": Permissions.MANAGE_SYSTEM},
            {"permission": Permissions.CREATE_USER},
            {"permission": Permissions.DELETE_USER},
            {"permission": Permissions.RENAME_USER},
            {"permission": Permissions.MANAGE_USER_STATUS},
            {"permission": Permissions.GET_USER_INFO},
            {"permission": Permissions.GET_GROUP_INFO},
            {"permission": Permissions.CHANGE_USER_GROUPS},
            {"permission": Permissions.SUPER_SET_PASSWD},
            {"permission": Permissions.VIEW_ACCESS_RULES},
            {"permission": Permissions.SET_ACCESS_RULES},
            {"permission": Permissions.LIST_USERS},
            {"permission": Permissions.LIST_GROUPS},
            {"permission": Permissions.CREATE_GROUP},
            {"permission": Permissions.DELETE_GROUP},
            {"permission": Permissions.RENAME_GROUP},
            {"permission": Permissions.SET_GROUP_PERMISSIONS},
            {"permission": Permissions.BYPASS_LOCKDOWN},
            {"permission": Permissions.APPLY_LOCKDOWN},
            {"permission": Permissions.VIEW_AUDIT_LOGS},
            {"permission": Permissions.MANAGE_ACCESS},
            {"permission": Permissions.VIEW_ACCESS_ENTRIES},
            {"permission": Permissions.BLOCK},
            {"permission": Permissions.UNBLOCK},
            {"permission": Permissions.SUPER_SET_USER_AVATAR},
            {"permission": Permissions.DEBUGGING},
            {"permission": Permissions.MANAGE_2FA},
            {"permission": Permissions.LIST_REVISIONS},
            {"permission": Permissions.VIEW_REVISION},
            {"permission": Permissions.SET_CURRENT_REVISION},
            {"permission": Permissions.DELETE_REVISION},
            {"permission": Permissions.MANAGE_KEYRINGS},
            {"permission": Permissions.LIST_USER_BLOCKS},
            {"permission": Permissions.PURGE},
            {"permission": Permissions.RESTORE},
            {"permission": Permissions.LIST_DELETED_ITEMS},
        ],
    )

    with Session() as session:
        init_file = File(id="init", path="./content/hello", active=True)
        session.add(init_file)

        init_document = Document(id="hello", title="Hello World")
        init_document_revision = DocumentRevision(file_id=init_file.id)
        init_document.revisions.append(init_document_revision)
        init_document.current_revision = init_document_revision
        session.add(init_document)
        session.add(init_document_revision)
        session.commit()

    from include.util.user import create_user
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.<>?/"
    password = "".join(secrets.choice(alphabet) for _ in range(16))

    create_user(
        username="admin",
        password=password,
        nickname="管理员",
        permissions=[],
        groups=[
            {
                "group_name": "sysop",
                "start_time": 0,
                "end_time": None,
            },
            {
                "group_name": "user",
                "start_time": 0,
                "end_time": None,
            },
        ],
    )

    # 将密码输出到运行目录下的 admin_password.txt 文件
    with open("admin_password.txt", "w", encoding="utf-8") as pwd_file:
        pwd_file.write(f"{password}\n")

    os.makedirs("./content", exist_ok=True)

    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    import datetime

    cert_path = global_config["server"]["ssl_certfile"]
    key_path = global_config["server"]["ssl_keyfile"]

    # 使用python包 cryptography 生成自签名证书和私钥
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):

        # 生成 ECC 私钥
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())

        # 生成自签名证书
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(
                    NameOID.COMMON_NAME, global_config["server"]["host"]
                ),
            ]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=DEFAULT_SSL_CERT_VALIDITY_DAYS)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName(global_config["server"]["host"])]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256(), default_backend())
        )

        # 写入私钥
        with open(key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # 写入证书
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open("./init", "w") as f:
        f.write("This file indicates that the database has been initialized.\n")

    ensure_root_folder()


def main():
    logger = getCustomLogger("CFMS", filepath="./content/logs/core.log")

    if not os.path.exists("./init"):
        logger.info("Database not initialized, initializing now...")
        server_init()

    logger.info("Initializating CFMS WebSocket server...")
    logger.info(f"CFMS Core Version: {CORE_VERSION}")
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(
        certfile=global_config["server"]["ssl_certfile"],
        keyfile=global_config["server"]["ssl_keyfile"],
    )
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3

    # Mutual TLS: require and verify client certificates if configured
    security_cfg = global_config.get("security", {})
    if security_cfg.get("require_client_cert", False):
        client_ca_path: str = security_cfg["client_cert_ca_path"]
        if not os.path.exists(client_ca_path) or not os.path.isdir(client_ca_path):
            logger.error(
                "Client certificate CA path not found or is not a dir: "
                f"{client_ca_path}. Cannot enable client certificate "
                "verification. Please provide a valid CA certificate "
                "path or disable 'require_client_cert' in the configuration."
            )
            raise SystemExit(1)
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        ssl_context.verify_flags |= ssl.VERIFY_X509_STRICT
        # ssl_context.verify_flags |= ssl.VERIFY_CRL_CHECK_LEAF
        # ssl_context.verify_flags |= ssl.VERIFY_CRL_CHECK_CHAIN

        ssl_context.load_verify_locations(capath=client_ca_path)
        logger.info(
            f"Mutual TLS enabled: client certificates will be verified "
            f"against CA path '{client_ca_path}'."
        )

    if ssl.OPENSSL_VERSION_INFO < (3, 5):
        logger.warning(
            "The version of OpenSSL bundled with Python is too low "
            f"({ssl.OPENSSL_VERSION}) and therefore **does not support"
            " post-quantum encryption**. Communication without post-quantum "
            'encryption may be vulnerable to "harvest now, decrypt later" '
            "attacks. Consider using a Python distribution that bundles "
            "OpenSSL 3.5 or later to resolve this issue."
        )

    # Always create tables that do not exist
    Base.metadata.create_all(engine)

    # Ensure the root folder record exists (handles upgrades from older versions)
    ensure_root_folder()

    # Preload banned subnet list into memory for LoginGuard
    LoginGuard.reload_networks()

    # DO NOT MODIFY socket family setting unless you know what you are doing
    socket_family = socket.AF_INET6

    with serve(
        handle_connection,
        global_config["server"]["host"],
        global_config["server"]["port"],
        ssl=ssl_context,
        family=socket_family,
        dualstack_ipv6=global_config["server"]["dualstack_ipv6"],
        process_request=global_process_request,
    ) as server:
        logger.info(
            f"CFMS WebSocket server started at wss://{global_config['server']['host']}:{global_config['server']['port']}"
        )  # TODO
        server.serve_forever()


if __name__ == "__main__":
    main()
