# Requirements-to-implementation traceability

Source precedence: the QR-specific design in `ProjectReportTask3.pdf`, then `ProjectReportTask2Final(2).pdf`, with compatible security/backup requirements retained from `ProjectReportFinal(3).pdf`. Earlier facial/RFID suggestions are superseded by the selected QR approach.

| Requirement | Delivered behavior | Implementation / test evidence |
| --- | --- | --- |
| FR-01 Automated attendance | A scanned session link opens login and automatically records the authenticated student's attendance | `/api/checkin`; backend `test_full_attendance_workflow`; frontend DOM workflow |
| FR-02 Manual override | Owning lecturer or admin adds/corrects a record, requires a reason and logs the change; failures can be queued locally | Session register → Correct; `test_expiry_offline_review_and_manual`, `test_excused_denominator_and_audit` |
| FR-03 Session creation | Create/activate lecture, test or exam sessions with course linkage and 1–240 minute expiry; end early | `/api/sessions`; `test_full_attendance_workflow` |
| FR-04 Correct student/class association | Server account identity, foreign keys and historical session rosters; enrollment checked | `db.py`, `attendance.py`; `test_role_and_course_boundaries`, `test_validation_and_roster_snapshots` |
| FR-05 Prevent duplicates | Composite attendance primary key; idempotent repeated scan | `test_full_attendance_workflow` |
| FR-06 RBAC | Student, lecturer and admin authorization checked in Python on every protected endpoint; lecturer course ownership enforced | `userManager.require`, `course_access`; `test_role_and_course_boundaries` |
| FR-07 Authorized history | Students see only their records; lecturers only assigned courses; admins all records; percentages include absences | Attendance page; `test_full_attendance_workflow`, `test_excused_denominator_and_audit` |
| FR-08 Reports | Course, student and UTC date filters, status and percentages; lecture/test/exam records | `/api/reports`; `test_exports_are_real_and_scoped` |
| FR-09 File exports | Genuine CSV and PDF downloads from server-filtered records | `reporting.py`; `test_exports_are_real_and_scoped`; PDF rendered and inspected |
| FR-10 Manage users | Admin creates, edits, changes unlinked roles, resets passwords and deactivates accounts; sessions invalidated | Users page; `test_user_management_revokes_sessions`; frontend admin flow |
| Authentication | PBKDF2 password hashes, signed HttpOnly sessions, CSRF checks, account-version revocation and login rate limits | `test_csrf_and_password_auth`, `test_rate_limit` |
| Two-factor authentication | Required for admins, opt-in for other users; real authenticator-app TOTP, expiring setup and replay protection | `test_admin_mfa_and_replay`; frontend TOTP enrollment |
| Profile management | View/update own name/email; password change requires current password | My profile; frontend profile flow |
| Course creation / enrollment | Lecturer creates own courses; admin assigns courses to lecturers; staff enroll existing student accounts | Courses page; roster snapshot test |
| QR API | Random token, SVG QR image, authenticated validation and expiry/closure | Session endpoints; `test_expired_token_and_wrong_roster` |
| Backups and recovery | Downloadable online SQLite snapshot, CLI backup, validated restore with pre-restore safety copy and session invalidation | System page / `manage.py`; `test_backup_restore_and_validation` |
| Local fallback / synchronization | Per-user localStorage queue, reconnection/manual synchronization; expired student submissions require lecturer review | `static/app.js`; frontend simulated outage/sync and backend pending-review test |
| Auditability | Course creation, session actions, manual corrections, user changes and backups recorded with actor and time | Admin System page; audit test |

## Non-functional requirements and limits

| Requirement | Implementation | Verification / remaining acceptance |
| --- | --- | --- |
| NFR-01 ≤15 seconds per student | Short authenticated POST and indexed SQLite relations | Local handler benchmark and test pass. Human login/scan time and campus concurrency are not yet measured. |
| NFR-02 Failure fallback | Local queue and manual corrections; consistent backups | Simulated network loss and recovery passed; actual device/network outage remains a venue test. |
| NFR-03 Protected student data | RBAC, password hashes, MFA, parameterized SQL, output escaping, CSRF, no-store API responses | Automated negative tests pass. HTTPS/private filesystem and backup policy are deployment responsibilities. |
| NFR-04 Simple responsive interface | Separate role navigation, labelled inputs, feedback, mobile media queries, keyboard focus | HTML/JS DOM workflows pass. Real browser/mobile visual and accessibility review remains pending. |
| NFR-05 Existing infrastructure | Python server + ordinary browser, phone camera and optional projector | LAN instructions included. Campus firewall/device isolation must be checked locally. |
| NFR-06 R540–R800 budget | No paid hosting, API, QR service or frontend build tool required | Software uses no per-request paid service. Actual hardware/network expenditure depends on available devices. |
| NFR-07 Maintainability | Separated Python modules, formatted JS/CSS, test suite and docs | Syntax checks and regression tests pass. |

## Deliberate design corrections

- Legacy database-design metadata is not a SQLite file; the new executable schema creates a real database on first run.
- The legacy socket server used a hard-coded LAN IP, demo plaintext credentials, no session enforcement, and almost no routes. Flask/Waitress now handles HTTP; SQLite holds accounts and records.
- The earlier user and SQL implementation was incomplete. `userManager.py` now handles password verification and access checks, while `db.py` owns persistence.
- The earlier HTML rendering approach had unimplemented function dispatch. A Jinja HTML shell and JavaScript render the working UI.
- A common displayed QR cannot safely contain a different student's identity for every scanner. The QR contains only the session token; authenticated server-side identity determines the student.
- Offline browser timestamps are not trusted as proof of in-class attendance. Expired queued scans create review requests, not automatic present records.
- Historical roster snapshots avoid changing old attendance percentages after enrollment changes.
- Existing role-linked histories are preserved by refusing incompatible role conversions. Deactivation plus a separate new-role account is supported.

## Main API endpoints

All mutation requests use JSON and the `X-CSRF-Token` from `/api/bootstrap`. Login and MFA refresh this token; cookie credentials stay same-origin. The backup endpoint is a POST returning binary SQLite data. Every `/api/` response uses `Cache-Control: no-store`.

| Method | Endpoint | Role / purpose |
| --- | --- | --- |
| GET | `/api/bootstrap` | Public; CSRF token and current account |
| POST | `/api/login`, `/api/logout` | Password login / end session |
| GET / POST | `/api/auth/setup`, `/api/auth/verify` | Pending MFA setup / code verification |
| GET / POST | `/api/profile` | View / update own account |
| POST | `/api/profile/2fa` | Start own MFA enrollment after password check |
| GET / POST | `/api/courses` | List permitted courses / staff course creation |
| GET / POST | `/api/courses/{id}/roster` | Staff view / add enrollment |
| GET / POST | `/api/sessions` | List permitted sessions / staff creation |
| GET | `/api/sessions/{id}` | Staff register, check-in link and pending requests |
| GET | `/api/sessions/{id}/qr` | Staff SVG QR for an active session |
| POST | `/api/sessions/{id}/close` | Staff closure |
| POST | `/api/checkin` | Student capture; `token`, optional boolean `offline` |
| POST | `/api/sessions/{id}/attendance` | Staff correction; `student_id`, `status`, `reason` |
| GET | `/api/reports` | Permitted history and summary |
| GET | `/api/reports/export` | CSV/PDF; `format`, `course_id`, `student_id`, `from`, `to` |
| GET / POST | `/api/users` | Admin list / create |
| POST | `/api/users/{id}` | Admin edit / deactivate / password reset |
| GET | `/api/audit` | Admin latest 200 events |
| POST | `/api/backup` | Admin consistent downloadable database backup |
