#!/usr/bin/env python3
"""
reset_password.py – CFMS maintenance script

Resets the password for a specific user directly in the database.

Usage:
    # Auto-generate a new password:
    python reset_password.py <username>

    # Manually specify a new password:
    python reset_password.py <username> --password <new_password>

This script must be run from the ``src/`` directory (same working directory as
``main.py``) so that ``config.toml`` and the database path are resolved
correctly.
"""

import argparse
import os
import secrets
import string
import sys


parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)


def _build_random_password(length: int = 16) -> str:
    """Return a cryptographically-random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.<>?/"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset a CFMS user's password from the command line."
    )
    parser.add_argument("username", help="Username whose password should be reset")
    parser.add_argument(
        "--password",
        metavar="NEW_PASSWORD",
        default=None,
        help=(
            "New password to set. "
            "If omitted a secure password is generated automatically."
        ),
    )
    args = parser.parse_args()

    username: str = args.username
    new_password: str = args.password if args.password else _build_random_password()

    # Validate that the caller is running from the src/ directory so that
    # conf_loader and the database can be found.
    if not os.path.exists("config.toml"):
        print(
            "Error: 'config.toml' not found in the current directory.\n"
            "Please run this script from the 'src/' directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Late imports so that the path check above can produce a clean error before
    # the import machinery tries to load config.toml.
    # All model modules must be imported before any session is used so that
    # SQLAlchemy can resolve the inter-model relationships that use string
    # forward references (e.g. "File", "UserKey", etc.).
    from include.database.handler import Session  # noqa: F401
    from include.database.models.classic import User  # noqa: F401
    from include.database.models.blocking import (
        UserBlockEntry,
        UserBlockSubEntry,
    )  # noqa: F401
    from include.database.models.file import File, FileTask  # noqa: F401
    from include.database.models.entity import (  # noqa: F401
        Document,
        DocumentRevision,
        Folder,
    )
    from include.database.models.keyring import UserKey  # noqa: F401

    with Session() as session:
        user = session.get(User, username)
        if user is None:
            print(f"Error: User '{username}' not found.", file=sys.stderr)
            sys.exit(1)

        user.set_password(new_password, force_update_after_login=True)
        # set_password commits via object_session; make sure the outer session
        # also persists the change in case object_session is different.
        session.add(user)
        session.commit()

    if args.password:
        print(f"Password for '{username}' has been updated successfully.")
    else:
        print(f"Password for '{username}' has been reset.")
        print(f"New password: {new_password}")
        print("Store this password in a safe place - it will not be shown again.")


if __name__ == "__main__":
    main()
