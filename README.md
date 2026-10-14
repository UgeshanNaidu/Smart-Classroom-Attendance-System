# Smart Classroom Attendance System (SCAS)

A working Python + HTML/CSS/JavaScript prototype for ENEL3SF. The Python server runs the actual authentication, attendance validation, database writes and exports. There is no Node.js build step and no external CDN dependency.

## Main Contributors:
- Ugeshan Naidu (224015440)
- Uzair Mahomed (224116082)
- Vahir Hurrienarain (224011818)
- Mohammed Khan (224024987)

## Start on Windows

1. Install **Python 3.10 or newer** if necessary.
2. Extract the complete ZIP, including the `fonts`, `static` and `templates` folders.
3. Double-click **start_windows.bat**. The first run downloads the Python dependencies.
4. Open **http://127.0.0.1:8080** in your browser. Leave the terminal window open.

Alternatively, in a terminal inside the extracted `scas` directory:

```sh
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
python -m pip install -r requirements.txt
python httpserver.py --demo
```

macOS/Linux:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
python httpserver.py --demo
```

Or run `bash start_mac_linux.sh`.

## Demo accounts

All demo accounts use **DemoPass123!**. Data and names are synthetic.

| Username | Role | Purpose |
| --- | --- | --- |
| `lecturer` | Lecturer | Manages ENEL3SF and its sessions |
| `student` | Student | Alex; enrolled in ENEL3SF and ENEL3DE |
| `student2` | Student | Sam; enrolled in ENEL3SF only |
| `lecturer2` | Lecturer | Manages ENEL3DE; cannot access ENEL3SF |
| `admin` | Administrator | Users, all courses, audit log and backups |

**Admin sign-in requires an authenticator app.** On first sign-in, add the displayed secret as a time-based (TOTP) account in your authenticator and enter its six-digit code. The secret is displayed once during enrollment; it is not a demo bypass. All users may enable 2FA in My profile. Computer and phone clocks should be set automatically. A used authenticator code cannot be reused; wait for the next code.

For the quickest demonstration, start with `lecturer` and use a private/incognito window for `student`. Different tabs in the same browser profile share the login cookie.

`--demo` seeds accounts only when the database has no users. Re-running the command preserves existing data. For a clean, non-demo installation, run `python manage.py create-admin`, then `python httpserver.py` without `--demo`.

## Suggested demonstration

1. Sign in as `lecturer`. Observe the seeded attendance history and dashboard.
2. Open **Courses → Manage roster**. New accounts can be enrolled by username before creating a session.
3. Select **New session**, choose ENEL3SF, enter a title and set a 15-minute window. Lecture, test and exam sessions are supported.
4. Display the QR code or copy the session link. The register refreshes every 10 seconds and has a manual refresh button.
5. Open that link in a private browser window. Sign in as `student`. Attendance is recorded automatically after sign-in, with a visible success message.
6. Submit the same token again. The existing record is returned; no duplicate is created.
7. In the lecturer window, correct a student's record and enter a reason. This appears in the audit log.
8. End the session. The QR code becomes invalid. Unrecorded students are counted absent.
9. Open **Attendance**, filter by course, student or date, and export CSV or an actual PDF.
10. Sign in as `admin`, enroll an authenticator, create/edit/deactivate a user, review the audit log, and download a backup.

## Phone / classroom access

Phones cannot use the laptop's `127.0.0.1` address. Connect both devices to the same network, find the laptop's LAN IPv4 address (`ipconfig` on Windows), and start:

```sh
python httpserver.py --demo --host 0.0.0.0 --port 8080
```

On the laptop **and** phone open `http://YOUR-LAPTOP-IP:8080`. QR links inherit the address used by the lecturer, so opening the lecturer dashboard through the LAN address matters. Allow Python through the firewall only for the trusted private network if prompted. Some campus Wi-Fi networks isolate devices; a trusted shared hotspot may be needed.

You can set an explicit canonical QR address using `SCAS_PUBLIC_URL`, for example in PowerShell:

```powershell
$env:SCAS_PUBLIC_URL = "http://192.168.1.45:8080"
python httpserver.py --demo --host 0.0.0.0
```

Use the phone's **normal camera app** to scan the QR. SCAS does not require an in-page camera or camera permission. A pasted link/token is also supported.

## Attendance rules

- QR tokens are random and session-specific; they contain no student ID or password.
- Identity comes from the authenticated account. Sending another student ID cannot register attendance for that student.
- Each session takes a snapshot of the active enrolled students. Later enrollments do not retroactively change historical percentages.
- First check-in during the first 10 minutes is `present`; later valid check-ins are `late`.
- One database primary key enforces one record per student per session.
- Session closing or expiry prevents new normal QR check-ins. Existing records remain viewable.
- A manual lecturer correction takes precedence. Scanning again cannot overwrite that correction.
- Percentage = `(present + late) / completed non-excused student-session records × 100`.
- Open sessions are excluded from the percentage; closed/expired sessions with no record count absent; excused records are excluded from numerator and denominator.
- Dates in the UI use the device timezone. Report date filters and exported timestamps use UTC, as labelled.
- Course coordinators use lecturer accounts assigned to their courses. Academic/IT administrators use the administrator role.

## Offline fallback

If a signed-in, already-loaded check-in form or manual correction form loses connection, the submission is kept in that browser's local storage, separately for each user ID. No password is queued. The **Offline queue** displays pending changes, synchronization errors, retry and discard controls. It synchronizes when the browser reports that connectivity returns, or when the user presses **Synchronize now**.

A queued submission is **not** a confirmed attendance record:

- An active-session student submission is validated normally after reconnecting.
- A student submission received after closure/expiry becomes a lecturer review request; it cannot establish trustworthy offline capture time.
- The lecturer opens the session, reviews the student and records present/late/absent/excused with a reason.
- Manual corrections synchronize only if the same signed-in account still has permission to manage that course.
- If the server restarts while the browser remains "online", use the explicit sync button after it returns.
- Offline login is not supported. After a full reload, reconnect and sign in as the same user to access the saved queue. Do not clear browser storage until synchronization completes.
- The service worker caches only the public app shell, never authenticated API responses. Shell caching requires HTTPS or localhost; it is not available on ordinary LAN HTTP. Loaded forms and their local queue still work on LAN HTTP.

## Backups and restoration

Admin → System → Download backup produces a consistent SQLite snapshot using the SQLite backup API, even while the app is running. It contains personal records and authentication secrets; keep it private.

Command-line backup:

```sh
python manage.py backup scas-backup.sqlite3
```

Use your OS scheduler to run the backup command periodically with a fresh filename. Scheduling and retention are deployment responsibilities.

Restore:

1. Stop the server with Ctrl+C.
2. Run `python manage.py restore scas-backup.sqlite3 --confirm`.
3. The tool validates the database/schema/references and saves a timestamped copy of the current database before replacement.
4. Start the server again. Restoring invalidates previous login sessions.

Lost authenticator recovery is deliberately a local server-admin operation:

```sh
python manage.py reset-2fa admin --confirm
```

Verify the account owner's identity first. This invalidates their sessions and forces a new admin authenticator enrollment on next sign-in. No email/password-recovery service is included.

## Architecture and files

| File | Responsibility |
| --- | --- |
| `httpserver.py` | Flask application, JSON endpoints, input validation, CSRF and command-line launch |
| `userManager.py` | Password hashing/verification, TOTP and role guards |
| `db.py` | SQLite schema, database lifecycle and optional synthetic demo data |
| `attendance.py` | Course/session permissions, history and percentage calculations |
| `reporting.py` | CSV/PDF generation from permission-filtered records |
| `htmlComposer.py` | Compatibility module for rendering the Jinja shell |
| `templates/index.html` | HTML application shell |
| `static/app.js` | Role-specific UI, form handling, offline queue and API requests |
| `static/style.css` | Responsive blue/white theme |
| `static/sw.js` | Public-shell offline cache |
| `manage.py` | Admin creation, backups, validated restoration and 2FA recovery |
| `tests/test_app.py` | Automated integration/security tests |
| `fonts/` | Bundled DejaVu fonts and license for portable PDF output |

SQLite data and the server-generated signing key are created in `instance/` on first run. They are excluded from the deliverable and Git ignore rules. Preserve them between runs. `SCAS_DATABASE` optionally chooses another database path. No migration of old attendance was attempted: legacy design metadata is not a populated SQLite database.

The reports' student and lecturer entities are represented by a role-constrained users table plus courses/enrollments, rather than duplicate identity tables. A many-to-many enrollment table supports more than one course per student. Historical rosters, pending review and audit tables were added to meet the operational requirements.

## Testing

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use fresh temporary databases and never touch the demo database. See `TEST_RESULTS.md` for verified cases and the remaining manual browser checklist. `REQUIREMENTS.md` maps FR-01 to FR-10 and the other report requirements to the implementation.

## Prototype boundaries

The project is intended for a local assignment demonstration. It is not a claim of completed campus deployment, security certification, POPIA compliance or stakeholder acceptance. Campus-scale load, a physical phone QR scan, and the full human check-in time must be verified in your venue.

For real accounts, remove demo users, use HTTPS through a configured reverse proxy, set `SCAS_HTTPS=1` for secure cookies, protect database/backup files, and set a private `SCAS_SECRET_KEY` or preserve the generated key. The server uses Waitress when installed. Avoid enabling Flask debug mode. QR sharing between students and account sharing remain possible; authenticated QR check-in is not physical-presence proof. Facial recognition, RFID, external LMS integration and biometric verification are not included because the later reports select QR capture.
