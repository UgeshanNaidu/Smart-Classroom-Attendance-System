"""Administrator CLI: create accounts, consistent backups, validated restore.
Stop the web server before restore. Backup can run while the server is running.
"""

import argparse
import getpass
import os
import sqlite3
import secrets
import time
from pathlib import Path
from httpserver import create_app
from db import initialize, get_db
from userManager import hash_password


def backup(source, target):
    target = Path(target)
    if target.exists():
        raise ValueError("Destination already exists; choose a new filename.")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return target


def restore(source, target):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target or not source.is_file():
        raise ValueError("Choose an existing, separate backup file.")
    required = {
        "users",
        "courses",
        "enrollments",
        "sessions",
        "session_students",
        "attendance",
        "pending",
        "audit",
        "login_attempts",
        "auth_setups",
    }
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed.")
        found = {
            r[0]
            for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not required.issubset(found):
            raise ValueError("Not a compatible SCAS backup.")
        if src.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Backup has invalid references.")
        expected = {
            "users": {"id", "username", "password_hash", "version", "totp_secret"},
            "sessions": {"token", "expires", "closed"},
            "attendance": {"session_id", "student_id", "status"},
        }
        for name, cols in expected.items():
            if not cols.issubset(
                {r[1] for r in src.execute(f"PRAGMA table_info({name})")}
            ):
                raise ValueError("Unsupported backup schema.")
        previous = None
        if target.exists():
            previous = backup(
                target, str(target) + ".before-restore-" + str(time.time_ns())
            )
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            dst.execute(
                "UPDATE users SET version=?", (secrets.randbelow(2**60) + 1000,)
            )
            dst.execute("DELETE FROM auth_setups")
        return previous
    finally:
        src.close()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("create-admin")
    b = sub.add_parser("backup")
    b.add_argument("path")
    r = sub.add_parser("restore")
    r.add_argument("path")
    r.add_argument("--confirm", action="store_true")
    t = sub.add_parser("reset-2fa")
    t.add_argument("username")
    t.add_argument("--confirm", action="store_true")
    args = p.parse_args()
    app = create_app()
    initialize(app)
    with app.app_context():
        db = get_db()
        if args.command == "create-admin":
            username = input("Admin username: ").strip()
            name = input("Full name: ").strip()
            password = getpass.getpass("Password (10+ characters): ")
            if len(password) < 10 or not username or not name:
                raise ValueError(
                    "Username, name and a 10+ character password are required."
                )
            if password != getpass.getpass("Confirm password: "):
                raise ValueError("Passwords differ.")
            db.execute(
                "INSERT INTO users(username,name,role,password_hash) VALUES (?,?,'admin',?)",
                (username, name, hash_password(password)),
            )
            db.commit()
            print(
                "Administrator created. Two-factor setup is required at first sign-in."
            )
        elif args.command == "backup":
            print("Backup saved:", backup(app.config["DATABASE"], args.path))
        elif args.command == "restore":
            if not args.confirm:
                raise ValueError(
                    "Stop SCAS, then add --confirm to restore. Current data will be replaced."
                )
            db.close()
            print(
                "Restored. Previous database:",
                restore(args.path, app.config["DATABASE"]),
            )
        elif args.command == "reset-2fa":
            if not args.confirm:
                raise ValueError("Verify account ownership, then add --confirm.")
            count = db.execute(
                "UPDATE users SET totp_secret=NULL,totp_last=-1,version=version+1 WHERE username=?",
                (args.username,),
            ).rowcount
            db.commit()
            if not count:
                raise ValueError("Account not found.")
            print("Authenticator reset. Existing sessions invalidated.")


if __name__ == "__main__":
    main()
