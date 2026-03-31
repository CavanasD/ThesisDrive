import ipaddress
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Union

from include.database.handler import Session
from include.database.models.security.banned_subnet import BannedSubnet
from include.database.models.security.login import LoginSecurity
from include.util.log import getCustomLogger

logger = getCustomLogger("login_guard", filepath="./content/logs/login_guard.log")


class LoginGuard:
    """
    A security guard for login attempts, designed to mitigate brute-force
    attacks by tracking failed attempts and temporarily blocking identifiers.
    """

    _mem_cache: dict[str, float] = {}  # { identifier: locked_until_timestamp }
    _cache_lock = threading.Lock()
    _MAX_CACHE_SIZE: int = 10_000

    _banned_networks: list[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
    _networks_loaded: bool = False

    @classmethod
    def reload_networks(cls) -> None:
        """
        Reload the banned subnet list from the database into memory.
        The database query is performed without holding the cache lock; the lock
        is only taken to swap in the new networks list and update state.
        """
        networks: list[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
        with Session() as session:
            rows = session.query(BannedSubnet).all()
            for row in rows:
                try:
                    networks.append(ipaddress.ip_network(row.subnet, strict=True))
                except ValueError:
                    logger.warning(
                        f"Ignoring invalid subnet in database: {row.subnet!r}"
                    )
        with cls._cache_lock:
            cls._banned_networks = networks
            cls._networks_loaded = True
            logger.info(
                f"Loaded {len(networks)} banned subnet(s) from database."
            )

    @classmethod
    def _extract_ip(cls, identifier: str) -> Optional[str]:
        parts = identifier.split("|", 2)
        if len(parts) >= 2:
            return parts[1] or None
        return None

    @classmethod
    def _is_ip_banned_by_subnet(cls, ip_str: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        with cls._cache_lock:
            # Copy reference to local list to minimize lock contention during iteration
            networks = cls._banned_networks

        return any(addr in network for network in networks)

    @classmethod
    def _prune_cache(cls, now_ts: float) -> None:
        """Callers must hold _cache_lock."""
        expired_keys = [
            key for key, expiry in cls._mem_cache.items() if expiry <= now_ts
        ]
        for key in expired_keys:
            cls._mem_cache.pop(key, None)

        if len(cls._mem_cache) > cls._MAX_CACHE_SIZE:
            sorted_items = sorted(cls._mem_cache.items(), key=lambda item: item[1])
            for key, _expiry in sorted_items:
                if len(cls._mem_cache) <= cls._MAX_CACHE_SIZE:
                    break
                cls._mem_cache.pop(key, None)

    @classmethod
    def check_access(cls, identifier: str) -> bool:
        """
        Check if the given identifier is currently blocked.
        """

        # Ensure networks are loaded before checking access.
        # reload_networks() is responsible for its own locking, so we avoid
        # taking _cache_lock here to prevent unnecessary complexity or deadlocks.
        if not cls._networks_loaded:
            cls.reload_networks()

        # Layer 1: CIDR / administratively banned subnet
        ip_str = cls._extract_ip(identifier)
        if ip_str and cls._is_ip_banned_by_subnet(ip_str):
            return False

        # Layer 2: in-memory cache
        now_ts = time.time()
        with cls._cache_lock:
            cls._prune_cache(now_ts)
            expiry = cls._mem_cache.get(identifier)
            if expiry:
                if now_ts < expiry:
                    return False
                else:
                    del cls._mem_cache[identifier]

        # Layer 3: database
        with Session() as session:
            record = session.get(LoginSecurity, identifier)
            if record is not None and record.is_locked():
                if record.locked_until is not None:
                    with cls._cache_lock:
                        cls._mem_cache[identifier] = record.locked_until.timestamp()
                    return False
        return True

    @classmethod
    def report_failure(
        cls, identifier: str, max_attempts: int = 5, lock_minutes: int = 15
    ):
        with Session() as session:
            record = session.get(LoginSecurity, identifier)
            now = datetime.now()

            if not record:
                record = LoginSecurity(identifier=identifier, failed_attempts=1)
                session.add(record)
            else:
                if record.last_attempt < now - timedelta(hours=1):
                    record.failed_attempts = 1
                else:
                    record.failed_attempts += 1
                record.last_attempt = now

            if record.failed_attempts >= max_attempts:
                lock_time = now + timedelta(minutes=lock_minutes)
                record.locked_until = lock_time
                lock_ts = lock_time.timestamp()
                with cls._cache_lock:
                    cls._prune_cache(time.time())
                    cls._mem_cache[identifier] = lock_ts
                logger.warning(
                    f"Security: identifier '{identifier}' locked until {lock_time}"
                )

            session.commit()

    @classmethod
    def report_success(cls, identifier: str):
        with Session() as session:
            record = session.get(LoginSecurity, identifier)
            if record:
                session.delete(record)
                session.commit()

            with cls._cache_lock:
                cls._mem_cache.pop(identifier, None)
