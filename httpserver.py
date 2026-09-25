"""SCAS application factory and command-line launcher.
Run `python httpserver.py --demo` for the assignment demonstration.
"""

import argparse
import io
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import qrcode
import qrcode.image.svg
from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException
from db import get_db, close_db, initialize, audit
from userManager import (
    hash_password,
    verify_password,
    require,
    public_user,
    new_secret,
    verify_totp,
)
from attendance import course_access, session_access, report_rows, summarize
from reporting import export

ROOT = Path(__file__).resolve().parent


def data():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(400, description="A JSON object is required.")
    return body


def field(body, key, maximum=120, required=True):
    value = body.get(key, "")
    if not isinstance(value, str):
        abort(400, description=f"{key} must be text.")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        abort(
            400,
            description=f"{key} is required and must be at most {maximum} characters.",
        )
    return value


def number(body, key, low=1, high=2147483647):
    try:
        value = int(body.get(key, ""))
        if isinstance(body.get(key), bool) or not low <= value <= high:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        abort(400, description=f"Invalid {key}.")


def create_app(config=None):
    app = Flask(__name__)
    instance = ROOT / "instance"
    instance.mkdir(exist_ok=True)
    secret_path = instance / "secret.key"
    if not secret_path.exists():
        try:
            fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    app.config.update(
        SECRET_KEY=os.getenv("SCAS_SECRET_KEY") or secret_path.read_text(),
        DATABASE=os.getenv("SCAS_DATABASE", str(instance / "scas.sqlite3")),
        MAX_CONTENT_LENGTH=128 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SCAS_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        PUBLIC_URL=os.getenv("SCAS_PUBLIC_URL", "").rstrip("/"),
    )
    if config:
        app.config.update(config)
    app.teardown_appcontext(close_db)

    @app.before_request
    def csrf_guard():
        if request.path.startswith("/api/") and request.method not in (
            "GET",
            "HEAD",
            "OPTIONS",
        ):
            if not session.get("csrf") or not secrets.compare_digest(
                session["csrf"], request.headers.get("X-CSRF-Token", "")
            ):
                abort(
                    403,
                    description="Security token expired. Refresh the page and try again.",
                )

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify(error=e.description), e.code

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(e):
        get_db().rollback()
        return (
            jsonify(
                error="This entry already exists or conflicts with related records."
            ),
            409,
        )

    @app.route("/")
    @app.route("/checkin")
    def index():
        return render_template("index.html")

    @app.get("/sw.js")
    def worker():
        return app.send_static_file("sw.js")

    @app.get("/api/bootstrap")
    def bootstrap():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        u = (
            get_db()
            .execute("SELECT * FROM users WHERE id=?", (session.get("uid"),))
            .fetchone()
        )
        if u and (not u["active"] or u["version"] != session.get("version")):
            u = None
        return jsonify(csrf=session["csrf"], user=public_user(u) if u else None)

    def rate_check(subject, limit=10):
        db = get_db()
        now = time.time()
        row = db.execute(
            "SELECT * FROM login_attempts WHERE subject=?", (subject,)
        ).fetchone()
        if row and now - row["since"] < 300 and row["count"] >= limit:
            abort(429, description="Too many sign-in attempts. Wait five minutes.")
        if not row or now - row["since"] >= 300:
            db.execute(
                "INSERT OR REPLACE INTO login_attempts VALUES (?,1,?)", (subject, now)
            )
        else:
            db.execute(
                "UPDATE login_attempts SET count=count+1 WHERE subject=?", (subject,)
            )
        db.commit()

    def signed_in(user):
        session.clear()
        session.permanent = True
        session.update(
            uid=user["id"], version=user["version"], csrf=secrets.token_urlsafe(32)
        )
        return jsonify(user=public_user(user), csrf=session["csrf"])

    @app.post("/api/login")
    def login():
        b = data()
        username = field(b, "username")
        password = field(b, "password", 200)
        rate_check("login:" + username.lower())
        rate_check("ip:" + str(request.remote_addr), 200)
        u = (
            get_db()
            .execute("SELECT * FROM users WHERE username=?", (username,))
            .fetchone()
        )
        if (
            not u
            or not u["active"]
            or not verify_password(password, u["password_hash"])
        ):
            abort(401, description="Invalid username or password.")
        get_db().execute(
            "DELETE FROM login_attempts WHERE subject=?", ("login:" + username.lower(),)
        )
        get_db().commit()
        session.pop("uid", None)
        if u["totp_secret"] or u["role"] == "admin":
            session["pending_uid"] = u["id"]
            session["pending_version"] = u["version"]
            session["pending_until"] = time.time() + 300
            session.pop("setup_key", None)
            return jsonify(
                two_factor_required=True, setup_required=not bool(u["totp_secret"])
            )
        return signed_in(u)

    @app.get("/api/auth/setup")
    def auth_setup():
        if session.get("pending_until", 0) < time.time():
            abort(401, description="Sign in again to set up authentication.")
        u = (
            get_db()
            .execute("SELECT * FROM users WHERE id=?", (session.get("pending_uid"),))
            .fetchone()
        )
        if not u or u["totp_secret"]:
            abort(403, description="Setup is not available.")
        db = get_db()
        setup = db.execute(
            "SELECT secret FROM auth_setups WHERE token=? AND user_id=? AND expires>?",
            (session.get("setup_key"), u["id"], time.time()),
        ).fetchone()
        if not setup:
            key = secrets.token_urlsafe(32)
            secret = new_secret()
            db.execute("DELETE FROM auth_setups WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT INTO auth_setups VALUES (?,?,?,?)",
                (key, u["id"], secret, time.time() + 300),
            )
            db.commit()
            session["setup_key"] = key
        else:
            secret = setup["secret"]
        uri = (
            "otpauth://totp/SCAS:"
            + u["username"]
            + "?"
            + urlencode({"secret": secret, "issuer": "SCAS"})
        )
        return jsonify(secret=secret, uri=uri)

    @app.post("/api/auth/verify")
    def auth_verify():
        b = data()
        rate_check("totp:" + str(session.get("pending_uid")))
        if session.get("pending_until", 0) < time.time():
            abort(401, description="Sign-in expired. Please start again.")
        db = get_db()
        u = db.execute(
            "SELECT * FROM users WHERE id=?", (session.get("pending_uid"),)
        ).fetchone()
        if not u or not u["active"] or session.get("pending_version") != u["version"]:
            abort(401, description="Account changed. Please sign in again.")
        setup = db.execute(
            "SELECT secret FROM auth_setups WHERE token=? AND user_id=? AND expires>?",
            (session.get("setup_key"), u["id"], time.time()),
        ).fetchone()
        secret = u["totp_secret"] or (setup["secret"] if setup else None)
        step = (
            verify_totp(secret, field(b, "code", 6), u["totp_last"]) if secret else None
        )
        if step is None:
            abort(
                400,
                description="Invalid or already-used code. Try the next authenticator code.",
            )
        changed = db.execute(
            "UPDATE users SET totp_secret=?,totp_last=? WHERE id=? AND totp_last<?",
            (secret, step, u["id"], step),
        ).rowcount
        if not changed:
            db.rollback()
            abort(400, description="Code already used. Wait for a new code.")
        db.execute("DELETE FROM auth_setups WHERE user_id=?", (u["id"],))
        db.commit()
        return signed_in(
            db.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
        )

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/profile")
    @require()
    def profile():
        return jsonify(user=public_user(g.user))

    @app.post("/api/profile")
    @require()
    def update_profile():
        b = data()
        db = get_db()
        name = field(b, "name")
        email = field(b, "email", 160, False)
        password = field(b, "new_password", 200, False)
        if password:
            if len(password) < 10:
                abort(400, description="Use at least 10 characters for the password.")
            if not verify_password(
                field(b, "current_password", 200), g.user["password_hash"]
            ):
                abort(400, description="Current password is incorrect.")
            db.execute(
                "UPDATE users SET password_hash=?,version=version+1 WHERE id=?",
                (hash_password(password), g.user["id"]),
            )
            session["version"] = g.user["version"] + 1
        db.execute(
            "UPDATE users SET name=?,email=? WHERE id=?", (name, email, g.user["id"])
        )
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/profile/2fa")
    @require()
    def enable_2fa():
        if g.user["totp_secret"]:
            abort(400, description="Two-factor authentication is already enabled.")
        if not verify_password(field(data(), "password", 200), g.user["password_hash"]):
            abort(400, description="Password is incorrect.")
        session["pending_uid"] = g.user["id"]
        session["pending_version"] = g.user["version"]
        session["pending_until"] = time.time() + 300
        return jsonify(ok=True)

    @app.get("/api/courses")
    @require()
    def courses():
        db = get_db()
        where = ""
        args = []
        if g.user["role"] == "lecturer":
            where = " WHERE c.lecturer_id=?"
            args = [g.user["id"]]
        if g.user["role"] == "student":
            where = (
                " WHERE c.id IN (SELECT course_id FROM enrollments WHERE student_id=?)"
            )
            args = [g.user["id"]]
        rows = db.execute(
            "SELECT c.*,u.name lecturer,(SELECT count(*) FROM enrollments e WHERE e.course_id=c.id) students FROM courses c JOIN users u ON u.id=c.lecturer_id"
            + where
            + " ORDER BY c.code",
            args,
        )
        return jsonify(courses=[dict(r) for r in rows])

    @app.post("/api/courses")
    @require("lecturer", "admin")
    def create_course():
        b = data()
        lecturer = (
            g.user["id"] if g.user["role"] == "lecturer" else number(b, "lecturer_id")
        )
        if (
            not get_db()
            .execute(
                "SELECT 1 FROM users WHERE id=? AND role='lecturer' AND active=1",
                (lecturer,),
            )
            .fetchone()
        ):
            abort(400, description="Select an active lecturer.")
        db = get_db()
        cur = db.execute(
            "INSERT INTO courses(code,name,lecturer_id) VALUES (?,?,?)",
            (field(b, "code", 30).upper(), field(b, "name"), lecturer),
        )
        audit(g.user["id"], "course.create", str(cur.lastrowid))
        db.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.get("/api/courses/<int:cid>/roster")
    @require("lecturer", "admin")
    def roster(cid):
        course_access(cid)
        return jsonify(
            students=[
                dict(r)
                for r in get_db().execute(
                    "SELECT u.id,u.username,u.name,u.active FROM users u JOIN enrollments e ON e.student_id=u.id WHERE e.course_id=? ORDER BY u.name",
                    (cid,),
                )
            ]
        )

    @app.post("/api/courses/<int:cid>/roster")
    @require("lecturer", "admin")
    def enroll(cid):
        course_access(cid)
        b = data()
        username = field(b, "username")
        db = get_db()
        u = db.execute(
            "SELECT * FROM users WHERE username=? AND role='student' AND active=1",
            (username,),
        ).fetchone()
        if not u:
            abort(400, description="Active student account not found.")
        db.execute("INSERT OR IGNORE INTO enrollments VALUES (?,?)", (cid, u["id"]))
        audit(g.user["id"], "enrollment.add", f'{cid}:{u["id"]}')
        db.commit()
        return jsonify(ok=True)

    @app.get("/api/sessions")
    @require()
    def sessions_list():
        db = get_db()
        where = ""
        args = []
        if g.user["role"] == "lecturer":
            where = " WHERE c.lecturer_id=?"
            args = [g.user["id"]]
        if g.user["role"] == "student":
            where = " WHERE EXISTS(SELECT 1 FROM session_students r WHERE r.session_id=s.id AND r.student_id=?)"
            args = [g.user["id"]]
        rows = db.execute(
            """SELECT s.id,s.course_id,s.title,s.kind,s.starts,s.expires,s.closed,c.code,
          (SELECT count(*) FROM session_students r WHERE r.session_id=s.id) expected,
          (SELECT count(*) FROM attendance a WHERE a.session_id=s.id AND a.status IN ('present','late')) attended
          FROM sessions s JOIN courses c ON c.id=s.course_id"""
            + where
            + " ORDER BY s.starts DESC",
            args,
        )
        return jsonify(
            sessions=[
                dict(r) | {"active": not r["closed"] and r["expires"] > time.time()}
                for r in rows
            ]
        )

    @app.post("/api/sessions")
    @require("lecturer", "admin")
    def create_session():
        b = data()
        cid = number(b, "course_id")
        course_access(cid)
        kind = field(b, "kind")
        if kind not in ("lecture", "test", "exam"):
            abort(400, description="Invalid session type.")
        minutes = number(b, "minutes", 1, 240)
        db = get_db()
        if not db.execute(
            "SELECT 1 FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.course_id=? AND u.active=1",
            (cid,),
        ).fetchone():
            abort(400, description="Enroll students before creating a session.")
        now = time.time()
        cur = db.execute(
            "INSERT INTO sessions(course_id,title,kind,starts,expires,token,created_by) VALUES (?,?,?,?,?,?,?)",
            (
                cid,
                field(b, "title"),
                kind,
                now,
                now + 60 * minutes,
                secrets.token_urlsafe(24),
                g.user["id"],
            ),
        )
        sid = cur.lastrowid
        db.execute(
            "INSERT INTO session_students SELECT ?,e.student_id FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.course_id=? AND u.active=1",
            (sid, cid),
        )
        audit(g.user["id"], "session.create", str(sid))
        db.commit()
        return jsonify(id=sid), 201

    @app.get("/api/sessions/<int:sid>")
    @require("lecturer", "admin")
    def session_detail(sid):
        s = session_access(sid)
        db = get_db()
        now = time.time()
        rows = db.execute(
            """SELECT u.id,u.username,u.name,a.status,a.source,a.reason FROM session_students r
          JOIN users u ON u.id=r.student_id LEFT JOIN attendance a ON a.student_id=u.id AND a.session_id=r.session_id
          WHERE r.session_id=? ORDER BY u.name""",
            (sid,),
        )
        url = (
            (app.config["PUBLIC_URL"] or request.host_url.rstrip("/"))
            + "/checkin?"
            + urlencode({"token": s["token"]})
        )
        return jsonify(
            session=dict(s) | {"active": not s["closed"] and s["expires"] > now},
            url=url,
            students=[
                dict(r)
                | {
                    "status": r["status"]
                    or (
                        "absent"
                        if s["closed"] or s["expires"] <= now
                        else "not yet recorded"
                    )
                }
                for r in rows
            ],
            pending=[
                dict(r)
                for r in db.execute(
                    "SELECT p.*,u.name FROM pending p JOIN users u ON u.id=p.student_id WHERE session_id=? AND p.status=?",
                    (sid, "pending"),
                )
            ],
        )

    @app.get("/api/sessions/<int:sid>/qr")
    @require("lecturer", "admin")
    def qr(sid):
        s = session_access(sid)
        if s["closed"] or s["expires"] <= time.time():
            abort(400, description="Session has ended.")
        url = (
            (app.config["PUBLIC_URL"] or request.host_url.rstrip("/"))
            + "/checkin?"
            + urlencode({"token": s["token"]})
        )
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
        stream = io.BytesIO()
        img.save(stream)
        stream.seek(0)
        return send_file(stream, mimetype="image/svg+xml")

    @app.post("/api/sessions/<int:sid>/close")
    @require("lecturer", "admin")
    def close_session(sid):
        session_access(sid)
        db = get_db()
        db.execute("UPDATE sessions SET closed=1 WHERE id=?", (sid,))
        audit(g.user["id"], "session.close", str(sid))
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/checkin")
    @require("student")
    def checkin():
        b = data()
        token = field(b, "token", 200)
        db = get_db()
        s = db.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
        if not s:
            abort(400, description="Invalid QR code or session token.")
        if not db.execute(
            "SELECT 1 FROM session_students WHERE session_id=? AND student_id=?",
            (s["id"], g.user["id"]),
        ).fetchone():
            abort(403, description="You are not on this session’s student roster.")
        existing = db.execute(
            "SELECT status FROM attendance WHERE session_id=? AND student_id=?",
            (s["id"], g.user["id"]),
        ).fetchone()
        if existing:
            return jsonify(
                message="Attendance already recorded: " + existing["status"],
                status=existing["status"],
            )
        if s["closed"] or s["expires"] <= time.time():
            if b.get("offline") is not True:
                abort(
                    400,
                    description="This session has ended. Ask your lecturer for a correction.",
                )
            db.execute(
                "INSERT OR IGNORE INTO pending(session_id,student_id,requested_at) VALUES (?,?,?)",
                (s["id"], g.user["id"], time.time()),
            )
            db.commit()
            return (
                jsonify(
                    status="pending",
                    message="Expired offline submission sent to your lecturer for review.",
                ),
                202,
            )
        # A write transaction rechecks expiry/closure so simultaneous closure cannot admit a scan.
        db.execute("BEGIN IMMEDIATE")
        s = db.execute("SELECT * FROM sessions WHERE id=?", (s["id"],)).fetchone()
        if s["closed"] or s["expires"] <= time.time():
            db.rollback()
            abort(
                409,
                description="Session just ended. Ask your lecturer for a correction.",
            )
        existing = db.execute(
            "SELECT status FROM attendance WHERE session_id=? AND student_id=?",
            (s["id"], g.user["id"]),
        ).fetchone()
        if existing:
            db.commit()
            return jsonify(
                message="Attendance already recorded: " + existing["status"],
                status=existing["status"],
            )
        status = "late" if time.time() - s["starts"] > 600 else "present"
        db.execute(
            "INSERT OR IGNORE INTO attendance VALUES (?,?,?,?,?,?,?)",
            (s["id"], g.user["id"], status, time.time(), "qr", "", g.user["id"]),
        )
        audit(g.user["id"], "attendance.scan", str(s["id"]))
        db.commit()
        return jsonify(status=status, message="Attendance recorded successfully."), 201

    @app.post("/api/sessions/<int:sid>/attendance")
    @require("lecturer", "admin")
    def manual(sid):
        session_access(sid)
        b = data()
        student = number(b, "student_id")
        status = field(b, "status")
        reason = field(b, "reason", 500)
        if status not in ("present", "late", "absent", "excused"):
            abort(400, description="Invalid attendance status.")
        db = get_db()
        if not db.execute(
            "SELECT 1 FROM session_students WHERE session_id=? AND student_id=?",
            (sid, student),
        ).fetchone():
            abort(400, description="Student is not on the session roster.")
        old = db.execute(
            "SELECT status FROM attendance WHERE session_id=? AND student_id=?",
            (sid, student),
        ).fetchone()
        db.execute(
            """INSERT INTO attendance VALUES (?,?,?,?,?,?,?) ON CONFLICT(session_id,student_id)
          DO UPDATE SET status=excluded.status,recorded_at=excluded.recorded_at,source=excluded.source,reason=excluded.reason,updated_by=excluded.updated_by""",
            (sid, student, status, time.time(), "manual", reason, g.user["id"]),
        )
        db.execute(
            "UPDATE pending SET status='reviewed' WHERE session_id=? AND student_id=?",
            (sid, student),
        )
        audit(
            g.user["id"],
            "attendance.override",
            f'{sid}:{student} {old[0] if old else "unrecorded"} -> {status}: {reason}',
        )
        db.commit()
        return jsonify(ok=True)

    def filtered_rows():
        cid = request.args.get("course_id")
        student = request.args.get("student_id")
        start = end = None
        try:
            if request.args.get("from"):
                start = (
                    datetime.strptime(request.args["from"], "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
            if request.args.get("to"):
                end = (
                    datetime.strptime(request.args["to"], "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    + timedelta(days=1)
                ).timestamp()
        except ValueError:
            abort(400, description="Dates must use YYYY-MM-DD.")
        if start and end and start >= end:
            abort(400, description="Start date must be before end date.")
        return report_rows(cid, student, start, end)

    @app.get("/api/reports")
    @require()
    def reports():
        rows = filtered_rows()
        return jsonify(rows=rows, summary=summarize(rows))

    @app.get("/api/reports/export")
    @require()
    def report_export():
        fmt = request.args.get("format", "csv")
        if fmt not in ("csv", "pdf"):
            abort(400, description="Choose CSV or PDF.")
        content, mime, ext = export(filtered_rows(), fmt)
        return send_file(
            io.BytesIO(content),
            mimetype=mime,
            as_attachment=True,
            download_name="attendance." + ext,
        )

    @app.get("/api/users")
    @require("admin")
    def users():
        return jsonify(
            users=[
                public_user(r)
                for r in get_db().execute("SELECT * FROM users ORDER BY name")
            ]
        )

    @app.post("/api/users")
    @require("admin")
    def add_user():
        b = data()
        password = field(b, "password", 200)
        role = field(b, "role")
        if len(password) < 10:
            abort(400, description="Passwords need at least 10 characters.")
        if role not in ("student", "lecturer", "admin"):
            abort(400, description="Invalid role.")
        username = field(b, "username", 60)
        if not all(c.isalnum() or c in "._-" for c in username):
            abort(
                400,
                description="Username may contain letters, digits, dot, underscore or hyphen.",
            )
        db = get_db()
        cur = db.execute(
            "INSERT INTO users(username,name,email,role,password_hash) VALUES (?,?,?,?,?)",
            (
                username,
                field(b, "name"),
                field(b, "email", 160, False),
                role,
                hash_password(password),
            ),
        )
        audit(g.user["id"], "user.create", str(cur.lastrowid))
        db.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.post("/api/users/<int:uid>")
    @require("admin")
    def edit_user(uid):
        b = data()
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            abort(404, description="User not found.")
        role = field(b, "role")
        active = number(b, "active", 0, 1)
        if role not in ("student", "lecturer", "admin"):
            abort(400, description="Invalid role.")
        if uid == g.user["id"] and (not active or role != "admin"):
            abort(400, description="You cannot remove your own administrator access.")
        if role != u["role"]:
            linked = db.execute(
                "SELECT 1 FROM courses WHERE lecturer_id=? UNION SELECT 1 FROM enrollments WHERE student_id=? UNION SELECT 1 FROM session_students WHERE student_id=?",
                (uid, uid, uid),
            ).fetchone()
            if linked:
                abort(
                    400,
                    description="This role has course/history links. Deactivate the account and create a new role account instead.",
                )
        password = field(b, "password", 200, False)
        if password and len(password) < 10:
            abort(400, description="Passwords need at least 10 characters.")
        db.execute(
            "UPDATE users SET name=?,email=?,role=?,active=?,version=version+1 WHERE id=?",
            (field(b, "name"), field(b, "email", 160, False), role, active, uid),
        )
        if password:
            db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (hash_password(password), uid),
            )
        if uid == g.user["id"]:
            session["version"] = u["version"] + 1
        audit(g.user["id"], "user.update", str(uid))
        db.commit()
        return jsonify(ok=True)

    @app.get("/api/audit")
    @require("admin")
    def audit_list():
        return jsonify(
            events=[
                dict(r)
                for r in get_db().execute(
                    "SELECT a.*,u.name actor FROM audit a LEFT JOIN users u ON a.actor_id=u.id ORDER BY a.id DESC LIMIT 200"
                )
            ]
        )

    @app.post("/api/backup")
    @require("admin")
    def backup():
        import tempfile

        db = get_db()
        audit(g.user["id"], "database.backup", "Created downloadable backup")
        db.commit()
        with tempfile.TemporaryDirectory() as folder:
            backup_path = Path(folder) / "backup.sqlite3"
            destination = sqlite3.connect(backup_path)
            db.backup(destination)
            destination.close()
            content = backup_path.read_bytes()
        return send_file(
            io.BytesIO(content),
            mimetype="application/vnd.sqlite3",
            as_attachment=True,
            download_name="scas-backup-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + ".sqlite3",
        )

    return app


def main():
    parser = argparse.ArgumentParser(description="Smart Classroom Attendance System")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Seed synthetic demo accounts if database is empty",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    app = create_app()
    initialize(app, args.demo)
    if args.demo:
        print(
            "Demo usernames: admin, lecturer, student, student2, lecturer2 | password: DemoPass123!"
        )
    print(f"SCAS: http://{args.host}:{args.port}")
    try:
        from waitress import serve

        serve(app, host=args.host, port=args.port)
    except ImportError:
        app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
