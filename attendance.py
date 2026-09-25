"""Course ownership, roster snapshots and attendance calculations."""

import time
from flask import abort, g
from db import get_db


def course_access(course_id):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if not course:
        abort(404, description="Course not found.")
    u = g.user
    if u["role"] == "lecturer" and course["lecturer_id"] != u["id"]:
        abort(403, description="This course belongs to another lecturer.")
    if (
        u["role"] == "student"
        and not db.execute(
            "SELECT 1 FROM enrollments WHERE course_id=? AND student_id=?",
            (course_id, u["id"]),
        ).fetchone()
    ):
        abort(403, description="You are not enrolled in this course.")
    return course


def session_access(sid):
    row = get_db().execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not row:
        abort(404, description="Session not found.")
    course_access(row["course_id"])
    return row


def report_rows(course_id=None, student_id=None, start=None, end=None):
    db = get_db()
    sql = """SELECT s.id session_id, c.code course, s.title, s.kind, s.starts,
        s.expires, s.closed, u.id student_id, u.username, u.name,
        a.status, a.recorded_at, a.source, a.reason
        FROM session_students r JOIN sessions s ON s.id=r.session_id
        JOIN courses c ON c.id=s.course_id JOIN users u ON u.id=r.student_id
        LEFT JOIN attendance a ON a.session_id=s.id AND a.student_id=u.id WHERE 1=1"""
    args = []
    if g.user["role"] == "lecturer":
        sql += " AND c.lecturer_id=?"
        args.append(g.user["id"])
    elif g.user["role"] == "student":
        sql += " AND u.id=?"
        args.append(g.user["id"])
    for clause, value in [("c.id", course_id), ("u.id", student_id)]:
        if value:
            sql += f" AND {clause}=?"
            args.append(value)
    if start is not None:
        sql += " AND s.starts>=?"
        args.append(start)
    if end is not None:
        sql += " AND s.starts<?"
        args.append(end)
    sql += " ORDER BY s.starts DESC,u.name"
    rows = []
    for record in db.execute(sql, args):
        r = dict(record)
        r["finalized"] = bool(r["closed"] or r["expires"] <= time.time())
        r["status"] = r["status"] or (
            "absent" if r["finalized"] else "not yet recorded"
        )
        rows.append(r)
    return rows


def summarize(rows):
    eligible = [r for r in rows if r["finalized"] and r["status"] != "excused"]
    attended = sum(r["status"] in ("present", "late") for r in eligible)
    return {
        "total": len(eligible),
        "attended": attended,
        "percentage": round(attended / len(eligible) * 100, 1) if eligible else None,
        "present": sum(r["status"] == "present" for r in rows),
        "late": sum(r["status"] == "late" for r in rows),
        "absent": sum(r["status"] == "absent" for r in rows),
    }
