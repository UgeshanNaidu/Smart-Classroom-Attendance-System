"""Integration tests using a fresh SQLite database for each test."""

import io
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from httpserver import create_app
from db import initialize, get_db
from userManager import totp
from manage import backup, restore


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.sqlite3"),
            "SECRET_KEY": "test-only",
        }
    )
    initialize(app, demo=True)
    return app


def post(client, path, body):
    csrf = client.get("/api/bootstrap").json["csrf"]
    return client.post("/api" + path, json=body, headers={"X-CSRF-Token": csrf})


def login(app, name):
    c = app.test_client()
    r = post(c, "/login", {"username": name, "password": "DemoPass123!"})
    assert r.status_code == 200
    if r.json.get("setup_required"):
        secret = c.get("/api/auth/setup").json["secret"]
        assert post(c, "/auth/verify", {"code": totp(secret)}).status_code == 200
    return c


def new_session(c):
    r = post(
        c,
        "/sessions",
        {"course_id": 1, "title": "Integration test", "kind": "lecture", "minutes": 15},
    )
    assert r.status_code == 201, r.json
    sid = r.json["id"]
    detail = c.get(f"/api/sessions/{sid}").json
    return sid, detail["session"]["token"]


def test_full_attendance_workflow(app):
    lecturer = login(app, "lecturer")
    student = login(app, "student")
    sid, token = new_session(lecturer)
    t = time.perf_counter()
    r = post(student, "/checkin", {"token": token})
    elapsed = time.perf_counter() - t
    assert r.status_code == 201 and r.json["status"] == "present"
    assert elapsed < 15
    assert post(student, "/checkin", {"token": token}).status_code == 200
    rows = lecturer.get(f"/api/sessions/{sid}").json["students"]
    assert rows[0]["status"] == "present"
    with app.app_context():
        assert (
            get_db()
            .execute("SELECT count(*) FROM attendance WHERE session_id=?", (sid,))
            .fetchone()[0]
            == 1
        )
    assert (
        post(
            lecturer,
            f"/sessions/{sid}/attendance",
            {"student_id": 3, "status": "late", "reason": "Arrived after roll call"},
        ).status_code
        == 200
    )
    assert post(lecturer, f"/sessions/{sid}/close", {}).status_code == 200
    r = student.get("/api/reports").json
    assert all(x["student_id"] == 3 for x in r["rows"])
    assert (
        r["summary"]["total"] == 5
        and r["summary"]["attended"] == 4
        and r["summary"]["percentage"] == 80
    )


def test_role_and_course_boundaries(app):
    lecturer = login(app, "lecturer")
    other = login(app, "lecturer2")
    student = login(app, "student")
    sid, token = new_session(lecturer)
    for path in [
        "/api/users",
        "/api/audit",
        f"/api/sessions/{sid}",
        f"/api/sessions/{sid}/qr",
    ]:
        assert student.get(path).status_code == 403
    assert other.get(f"/api/sessions/{sid}").status_code == 403
    assert post(other, f"/sessions/{sid}/close", {}).status_code == 403
    assert post(student, "/sessions", {"course_id": 1}).status_code == 403
    assert (
        post(student, "/checkin", {"token": token, "student_id": 4}).status_code == 201
    )
    with app.app_context():
        assert (
            get_db()
            .execute("SELECT student_id FROM attendance WHERE session_id=?", (sid,))
            .fetchone()[0]
            == 3
        )
    assert all(r["course"] == "ENEL3DE" for r in other.get("/api/reports").json["rows"])
    assert student.get("/api/reports?student_id=4").json["rows"] == []


def test_expiry_offline_review_and_manual(app):
    lecturer = login(app, "lecturer")
    student = login(app, "student")
    sid, token = new_session(lecturer)
    post(lecturer, f"/sessions/{sid}/close", {})
    assert post(student, "/checkin", {"token": token}).status_code == 400
    r = post(student, "/checkin", {"token": token, "offline": True})
    assert r.status_code == 202
    assert (
        post(student, "/checkin", {"token": token, "offline": True}).status_code == 202
    )
    d = lecturer.get(f"/api/sessions/{sid}").json
    assert len(d["pending"]) == 1
    assert not any(x["status"] == "present" for x in d["students"])
    assert (
        post(
            lecturer,
            f"/sessions/{sid}/attendance",
            {
                "student_id": 3,
                "status": "present",
                "reason": "Confirmed in classroom during outage",
            },
        ).status_code
        == 200
    )
    assert lecturer.get(f"/api/sessions/{sid}").json["pending"] == []


def test_expired_token_and_wrong_roster(app):
    l = login(app, "lecturer")
    s = login(app, "student")
    sid, token = new_session(l)
    with app.app_context():
        db = get_db()
        db.execute("UPDATE sessions SET expires=? WHERE id=?", (time.time() - 1, sid))
        db.commit()
    assert post(s, "/checkin", {"token": token}).status_code == 400
    assert l.get(f"/api/sessions/{sid}/qr").status_code == 400
    assert post(s, "/checkin", {"token": "invalid"}).status_code == 400
    other = login(app, "lecturer2")
    r = post(
        other,
        "/sessions",
        {"course_id": 2, "title": "Other course", "kind": "test", "minutes": 15},
    )
    assert r.status_code == 201
    token2 = other.get("/api/sessions/" + str(r.json["id"])).json["session"]["token"]
    assert (
        post(login(app, "student2"), "/checkin", {"token": token2}).status_code == 403
    )


def test_csrf_and_password_auth(app):
    c = app.test_client()
    assert (
        c.post(
            "/api/login", json={"username": "student", "password": "DemoPass123!"}
        ).status_code
        == 403
    )
    assert (
        post(c, "/login", {"username": "' OR 1=1 --", "password": "wrong"}).status_code
        == 401
    )
    assert c.get("/api/courses").status_code == 401
    c = login(app, "student")
    assert post(c, "/logout", {}).status_code == 200
    assert c.get("/api/reports").status_code == 401


def test_admin_mfa_and_replay(app):
    c = app.test_client()
    r = post(c, "/login", {"username": "admin", "password": "DemoPass123!"})
    assert r.json["setup_required"]
    assert c.get("/api/users").status_code == 401
    # A protected request clears incomplete auth; restart the intentional sign-in flow.
    post(c, "/login", {"username": "admin", "password": "DemoPass123!"})
    secret = c.get("/api/auth/setup").json["secret"]
    with c.session_transaction() as sess:
        assert secret not in str(dict(sess))
    assert post(c, "/auth/verify", {"code": "invalid"}).status_code == 400
    code = totp(secret)
    assert post(c, "/auth/verify", {"code": code}).status_code == 200
    assert c.get("/api/users").status_code == 200
    post(c, "/logout", {})
    r = post(c, "/login", {"username": "admin", "password": "DemoPass123!"})
    assert r.json["two_factor_required"] and not r.json["setup_required"]
    assert post(c, "/auth/verify", {"code": code}).status_code == 400


def test_user_management_revokes_sessions(app):
    admin = login(app, "admin")
    s = login(app, "student")
    assert (
        post(
            admin,
            "/users",
            {
                "username": "new",
                "name": "New Student",
                "email": "new@example.com",
                "role": "student",
                "password": "Password123!",
            },
        ).status_code
        == 201
    )
    assert (
        post(
            admin,
            "/users/3",
            {"name": "Alex", "email": "", "role": "student", "active": 0},
        ).status_code
        == 200
    )
    assert s.get("/api/courses").status_code == 401
    assert (
        post(
            admin,
            "/users/1",
            {"name": "Admin", "email": "", "role": "student", "active": 0},
        ).status_code
        == 400
    )
    assert (
        post(
            admin,
            "/users/2",
            {"name": "Lecturer", "email": "", "role": "student", "active": 1},
        ).status_code
        == 400
    )


def test_exports_are_real_and_scoped(app):
    s = login(app, "student")
    c = login(app, "lecturer")
    pdf = s.get("/api/reports/export?format=pdf")
    assert pdf.data.startswith(b"%PDF-")
    csv = s.get("/api/reports/export?format=csv")
    assert b"Alex Naidoo" in csv.data and b"Sam Mokoena" not in csv.data
    assert b"Sam Mokoena" in c.get("/api/reports/export?format=csv&student_id=4").data
    assert (
        b"Alex Naidoo" not in c.get("/api/reports/export?format=csv&student_id=4").data
    )
    assert s.get("/api/reports?from=wrong").status_code == 400
    assert s.get("/api/reports?from=2099-01-01").json["rows"] == []
    assert s.get("/api/reports/export?format=exe").status_code == 400


def test_backup_restore_and_validation(app, tmp_path):
    c = login(app, "admin")
    r = post(c, "/backup", {})
    assert r.status_code == 200 and r.data.startswith(b"SQLite format 3")
    p = tmp_path / "backup.sqlite3"
    p.write_bytes(r.data)
    with app.app_context():
        db = get_db()
        db.execute("UPDATE users SET name='Changed' WHERE id=3")
        db.commit()
    previous = restore(p, app.config["DATABASE"])
    assert previous.exists()
    with sqlite3.connect(app.config["DATABASE"]) as db:
        assert (
            db.execute("SELECT name FROM users WHERE id=3").fetchone()[0]
            == "Alex Naidoo"
        )
    assert c.get("/api/users").status_code == 401
    bad = tmp_path / "bad.sqlite3"
    sqlite3.connect(bad).close()
    with pytest.raises(ValueError):
        restore(bad, app.config["DATABASE"])


def test_validation_and_roster_snapshots(app):
    c = login(app, "lecturer")
    sid, token = new_session(c)
    assert (
        post(
            c,
            "/sessions",
            {"course_id": 1, "title": "", "kind": "lecture", "minutes": 0},
        ).status_code
        == 400
    )
    assert (
        post(
            c,
            f"/sessions/{sid}/attendance",
            {"student_id": 3, "status": "present", "reason": ""},
        ).status_code
        == 400
    )
    admin = login(app, "admin")
    new = post(
        admin,
        "/users",
        {
            "username": "latejoin",
            "name": "Late Join",
            "role": "student",
            "password": "Password123!",
        },
    ).json["id"]
    assert post(c, "/courses/1/roster", {"username": "latejoin"}).status_code == 200
    assert len(c.get(f"/api/sessions/{sid}").json["students"]) == 2
    new_sid, _ = new_session(c)
    assert len(c.get(f"/api/sessions/{new_sid}").json["students"]) == 3


def test_excused_denominator_and_audit(app):
    c = login(app, "lecturer")
    s = login(app, "student")
    admin = login(app, "admin")
    post(
        c,
        "/sessions/3/attendance",
        {"student_id": 3, "status": "excused", "reason": "Approved absence"},
    )
    summary = s.get("/api/reports").json["summary"]
    assert summary["percentage"] == 100 and summary["total"] == 3
    events = admin.get("/api/audit").json["events"]
    assert any("Approved absence" in e["detail"] for e in events)


def test_rate_limit(app):
    c = app.test_client()
    for _ in range(10):
        assert (
            post(c, "/login", {"username": "student", "password": "wrong"}).status_code
            == 401
        )
    assert (
        post(c, "/login", {"username": "student", "password": "wrong"}).status_code
        == 429
    )
