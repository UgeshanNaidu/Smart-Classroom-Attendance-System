# Verification results

Verified on 25 September 2026 in the development execution environment, using Python 3.12. The supported minimum is Python 3.10. Dependencies were Flask 3.1.3, qrcode 8.2, ReportLab 4.x and Waitress 3.0.2.

## Backend integration/security suite

`python -m pytest -q` — **12 passed**.

Tests cover:

1. Complete session/check-in/correction/closure flow; accurate percentage and unique record.
2. Student/staff/admin boundaries, lecturer course ownership and student identity spoof rejection.
3. Expired offline check-ins held for lecturer review; deduplicated pending requests; resolution.
4. Time-expired codes, invalid tokens, closed QR generation and non-enrolled students.
5. CSRF, failed authentication, SQL-injection-style username and logout access denial.
6. Mandatory admin authenticator enrollment, code validation, replay rejection and keeping setup secrets out of cookies.
7. User creation/deactivation, session revocation, self-admin protection and role-linked history protection.
8. Real CSV/PDF output, per-student scoping, date validation and unsupported format rejection.
9. Downloaded SQLite backup, restore/recovery, safety copy, invalid backup rejection and session invalidation.
10. Invalid input, mandatory override reason and historical roster snapshots after new enrollment.
11. Excused record denominator and correction audit details.
12. Failed-login rate limiting.

## Frontend DOM-to-server integration

`tests/frontend.cjs` ran against a real local Waitress/Python server with a disposable demo database. It executes the shipped frontend in jsdom with standard dialog shims. **Passed**, with no DOM runtime errors in the tested flows:

- Lecturer login and dashboard.
- Session creation and generated QR link.
- Student login through the link and automatic attendance capture.
- Duplicate scan feedback and lecturer register refresh.
- Manual correction with a reason.
- Simulated network failure, local queue, explicit synchronization and removal after success.
- Session closure.
- Student-scoped attendance page.
- Profile update reflected in the account header.
- Administrator first-login TOTP enrollment.
- Administrator user creation, audit list and backup UI availability.

jsdom does not lay out or render a real browser and does not emulate service-worker installation or a phone camera. These results are functional DOM checks, not a claim of full browser acceptance.

To repeat, install Node.js plus jsdom (`npm install --no-save jsdom`), start the server with `--demo` and a fresh disposable `SCAS_DATABASE`, then run `node tests/frontend.cjs`. Set `SCAS_TEST_URL` if using another port. The test creates records and enrolls the demo admin's authenticator, so do not run it against data you intend to keep.

## Performance observation

Twenty distinct, already-authenticated students submitted new check-ins through the Flask test client:

- Mean request handling: **1.53 ms**.
- Maximum observed: **3.54 ms**.

This excludes camera scanning, typing, login, network transport and campus-scale concurrency. It supports fast local processing, not a measured end-to-end 15-second classroom guarantee.

## Exports and syntax

- Python compilation and JavaScript syntax checks passed.
- PDF export generated multiple pages with repeated table headers, bundled fonts and wrapped text; a rendered page was inspected.
- CSV bytes include a UTF-8 BOM and formula-injection mitigation for user-controlled leading characters.
- Source was formatted with Black and Prettier; these are development tools, not runtime requirements.

## Remaining manual acceptance checks

The provided cloud browser could not reach the local Python server. A real browser visual/mobile test was therefore unavailable here. Run these on your machine:

- Open the app in Chrome/Edge/Firefox; verify the login, dashboards, dialogs, tables and keyboard focus.
- At approximately 390 px width, confirm the navigation scrolls and tables remain usable without page-wide overflow.
- Scan a newly created QR from an actual phone on the same network and confirm the correct account/session result.
- Confirm live register refresh within approximately 10 seconds.
- With a form already open, disconnect the network, submit, reconnect and synchronize.
- Repeat with the session expired before synchronization and confirm lecturer review is required.
- Test application-shell caching on localhost or HTTPS; ordinary LAN HTTP cannot register a service worker.
- Open downloaded CSV in a spreadsheet application and PDF in a PDF viewer.
- On Windows, verify the double-click launcher, backup download and stopped-server restore.
- Run representative classroom concurrency, end-to-end timing and stakeholder usability acceptance.
