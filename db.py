"""SQLite persistence, schema and reproducible demonstration data."""

import sqlite3
import time
from pathlib import Path
from flask import current_app, g

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
 name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', role TEXT NOT NULL
 CHECK(role IN ('student','lecturer','admin')), password_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, totp_secret TEXT, totp_last INTEGER DEFAULT -1,
 version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS courses (
 id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 lecturer_id INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS enrollments (
 course_id INTEGER REFERENCES courses(id), student_id INTEGER REFERENCES users(id),
 PRIMARY KEY(course_id,student_id));
CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
 title TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('lecture','test','exam')),
 starts REAL NOT NULL, expires REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0,
 token TEXT UNIQUE NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS session_students (
 session_id INTEGER REFERENCES sessions(id), student_id INTEGER REFERENCES users(id),
 PRIMARY KEY(session_id,student_id));
CREATE TABLE IF NOT EXISTS attendance (
 session_id INTEGER NOT NULL REFERENCES sessions(id), student_id INTEGER NOT NULL REFERENCES users(id),
 status TEXT NOT NULL CHECK(status IN ('present','late','absent','excused')),
 recorded_at REAL NOT NULL, source TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
 updated_by INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(session_id,student_id));
CREATE TABLE IF NOT EXISTS pending (
 id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id),
 student_id INTEGER REFERENCES users(id), requested_at REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', UNIQUE(session_id,student_id));
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
 detail TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_setups (
 token TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), secret TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (
 subject TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0, since REAL NOT NULL);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def audit(actor, action, detail):
    get_db().execute(
        "INSERT INTO audit(actor_id,action,detail,created_at) VALUES (?,?,?,?)",
        (actor, action, detail, time.time()),
    )


def initialize(app, demo=False):
    from userManager import hash_password
    import secrets

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if demo and not db.execute("SELECT 1 FROM users").fetchone():
            accounts = [
                ("admin", "System Administrator", "admin"),
                ("lecturer", "Dr Naledi Dlamini", "lecturer"),
                ("student", "Alex Naidoo", "student"),
                ("student2", "Sam Mokoena", "student"),
                ("lecturer2", "Dr Aisha Khan", "lecturer"),
            ]
            for username, name, role in accounts:
                db.execute(
                    "INSERT INTO users(username,name,email,role,password_hash) VALUES (?,?,?,?,?)",
                    (
                        username,
                        name,
                        username + "@scas.example",
                        role,
                        hash_password("DemoPass123!"),
                    ),
                )
            db.execute(
                "INSERT INTO courses VALUES (1,'ENEL3SF','Software Engineering 2',2)"
            )
            db.execute(
                "INSERT INTO courses VALUES (2,'ENEL3DE','Digital Electronics',5)"
            )
            db.executemany(
                "INSERT INTO enrollments VALUES (?,?)", [(1, 3), (1, 4), (2, 3)]
            )
            for i in range(1, 5):
                start = time.time() - i * 86400
                db.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        i,
                        1,
                        [
                            "Architecture workshop",
                            "Requirements review",
                            "Design patterns",
                            "Project introduction",
                        ][i - 1],
                        "lecture",
                        start,
                        start + 3600,
                        1,
                        secrets.token_urlsafe(24),
                        2,
                    ),
                )
                db.executemany(
                    "INSERT INTO session_students VALUES (?,?)", [(i, 3), (i, 4)]
                )
                db.execute(
                    "INSERT INTO attendance VALUES (?,?,?,?,?,?,?)",
                    (
                        i,
                        3,
                        "absent" if i == 3 else "present",
                        start + 60,
                        "demo",
                        "",
                        2,
                    ),
                )
                db.execute(
                    "INSERT INTO attendance VALUES (?,?,?,?,?,?,?)",
                    (i, 4, "late" if i == 2 else "present", start + 70, "demo", "", 2),
                )
            db.commit()
