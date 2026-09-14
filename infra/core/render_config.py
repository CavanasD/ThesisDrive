from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from tomlkit import dumps, parse

SAMPLE = Path("/app/src/config.toml.sample")
TARGET = Path("/app/state/config.toml")


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def env_bool(name: str, default: bool) -> bool:
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def overlay(target, current):
    for key, value in current.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            overlay(target[key], value)
        else:
            target[key] = value


config = parse(SAMPLE.read_text(encoding="utf-8"))
if TARGET.exists():
    overlay(config, parse(TARGET.read_text(encoding="utf-8")))
for identifier in ("drive", "transfer_data_plane", "thesis_attack_lab", "src_portal"):
    if identifier not in config["extensions"]["enabled"]:
        config["extensions"]["enabled"].append(identifier)

config["debug"] = env_bool("CFMS_DEBUG", False)
config["server"]["host"] = "0.0.0.0"
config["server"]["port"] = int(env("CFMS_PORT", "5104"))
config["server"]["dualstack_ipv6"] = False

config["database"]["type"] = "mysql"
config["database"]["host"] = env("MYSQL_HOST", "mysql")
config["database"]["port"] = int(env("MYSQL_PORT", "3306"))
config["database"]["username"] = env("MYSQL_USER", "thesis")
config["database"]["password"] = env("MYSQL_PASSWORD", "")
config["database"]["name"] = env("MYSQL_DATABASE", "thesis_drive")

config["provider"]["caching"] = "redis"
config["provider"]["event_bus"] = "redis"
config["provider"]["storage"] = "s3"
config["redis"]["host"] = env("REDIS_HOST", "redis")
config["redis"]["port"] = int(env("REDIS_PORT", "6379"))
config["redis"]["password"] = env("REDIS_PASSWORD", "")
config["s3"]["bucket"] = env("MINIO_BUCKET", "thesis-drive")
config["s3"]["endpoint_url"] = env("MINIO_ENDPOINT", "http://minio:9000")
config["s3"]["access_key_id"] = env("MINIO_ACCESS_KEY", "thesis-minio")
config["s3"]["secret_access_key"] = env("MINIO_SECRET_KEY", "")
config["s3"]["region_name"] = env("MINIO_REGION", "us-east-1")
config["s3"]["addressing_style"] = "path"

config["transfer"]["enabled"] = True
config["transfer"]["legacy_websocket_enabled"] = env_bool(
    "CFMS_LEGACY_WEBSOCKET_TRANSFER", False
)
config["transfer"]["base_url"] = env("CFMS_TRANSFER_BASE_URL", "")
config["transfer"]["private_key_file"] = env(
    "CFMS_TRANSFER_PRIVATE_KEY_FILE", "/run/transfer-private/private.pem"
)
config["transfer"]["consumer_name"] = env(
    "CFMS_TRANSFER_CONSUMER_NAME", "drive-core-1"
)

TARGET.parent.mkdir(parents=True, exist_ok=True)
temporary = TARGET.with_suffix(".tmp")
temporary.write_text(dumps(config), encoding="utf-8")
temporary.replace(TARGET)
