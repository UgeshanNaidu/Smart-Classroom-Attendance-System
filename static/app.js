"use strict";
const $ = (s) => document.querySelector(s),
  app = $("#app");
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const date = (t) =>
  new Date(t * 1000).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
const badge = (s) =>
  `<span class="tag ${esc(s).replace(/[^a-z]/g, "")}">${esc(s)}</span>`;
const input = (name, label, type = "text", value = "", required = true) =>
  `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${required ? "required" : ""} ${type === "password" ? 'autocomplete="current-password"' : ""}></label>`;
const select = (name, label, items, value) =>
  `<label class="field"><span>${label}</span><select name="${name}">${items.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
const table = (head, rows, empty = "No records to display.") =>
  rows.length
    ? `<div class="table-wrap"><table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : `<div class="empty">${empty}</div>`;
let csrf = "",
  user = null,
  page = "dashboard",
  courseList = [],
  sessionList = [],
  currentSession = null,
  reportQuery = "",
  noticeTimer;
let displayedSessionId = null;
let pendingToken = new URLSearchParams(location.search).get("token");
function toast(text) {
  $("#notice").textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => ($("#notice").textContent = ""), 6000);
}
async function api(path, body) {
  let response;
  try {
    response = await fetch("/api" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    e.network = true;
    throw e;
  }
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || "Request failed.");
    error.status = response.status;
    throw error;
  }
  if (result.csrf) csrf = result.csrf;
  return result;
}
function formBind(id, handler) {
  $(id).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.currentTarget,
      button = f.querySelector('button[type="submit"]'),
      err = f.querySelector(".form-error");
    if (err) err.innerHTML = "";
    if (button) button.disabled = true;
    try {
      await handler(Object.fromEntries(new FormData(f)), f);
    } catch (error) {
      if (err) err.innerHTML = `<div class="error">${esc(error.message)}</div>`;
      else toast(error.message);
    } finally {
      if (button) button.disabled = false;
    }
  });
}
function modal(html) {
  $("#modal-content").innerHTML = html;
  $("#modal").showModal();
}
$("#modal-close").onclick = () => $("#modal").close();
function queueKey() {
  return "scas-queue-" + user.id;
}
function queue() {
  try {
    return JSON.parse(localStorage.getItem(queueKey()) || "[]");
  } catch {
    return [];
  }
}
function saveQueue(items) {
  localStorage.setItem(queueKey(), JSON.stringify(items));
}
function addQueue(item) {
  const items = queue();
  if (
    !items.some(
      (i) =>
        i.path === item.path &&
        JSON.stringify(i.body) === JSON.stringify(item.body),
    )
  )
    items.push({
      ...item,
      id: Date.now().toString(36) + "-" + Math.random().toString(36).slice(2),
      created: Date.now(),
    });
  saveQueue(items);
  toast("Saved on this device. Open Offline queue to sync when connected.");
}
async function submitOrQueue(path, body) {
  try {
    return await api(path, body);
  } catch (e) {
    if (!e.network) throw e;
    addQueue({
      path,
      body: path === "/checkin" ? { ...body, offline: true } : body,
    });
    return {
      queued: true,
      message:
        "Saved on this device. Attendance is not confirmed until synchronized.",
    };
  }
}
function loginScreen() {
  app.innerHTML = `<div class="login"><section class="intro"><div class="brand"><span class="brandmark">▦</span> SCAS</div><div class="eyebrow">SMART CLASSROOM ATTENDANCE</div><h1>Less admin.<br>More learning.</h1><p>One place to capture attendance, follow progress and keep your classroom connected.</p><small>ENEL3SF · Software Engineering 2</small></section><section class="login-side"><div class="login-card"><div class="eyebrow">WELCOME TO YOUR CLASSROOM</div><h1>Sign in to SCAS</h1><p class="muted">Use your student or staff account to continue.</p>${pendingToken ? '<p class="hint">Your session QR code is ready. Sign in to record your attendance.</p>' : ""}<form id="login-form">${input("username", "Username / student number")}${input("password", "Password", "password")}<div class="form-error"></div><button class="wide" type="submit">Sign in →</button></form><p class="muted"><small>Need an account? Contact your system administrator.</small></p><footer>Secure access · Student, lecturer and administrator portals</footer></div></section></div>`;
  formBind("#login-form", async (b) => {
    const r = await api("/login", b);
    if (r.two_factor_required) return twoFactor(r.setup_required);
    user = r.user;
    await enter();
  });
}
async function twoFactor(setup) {
  let s = null;
  if (setup) s = await api("/auth/setup");
  const box = $(".login-card") || $("main");
  box.innerHTML = `<div class="eyebrow">ACCOUNT SECURITY</div><h1>${setup ? "Set up two-factor authentication" : "Verify your sign-in"}</h1><p class="muted">${setup ? "Add a time-based account in your authenticator app using this setup key." : "Enter the six-digit code from your authenticator app."}</p>${s ? `<div class="hint"><strong>Account: ${esc(user?.username || "SCAS")}</strong><p class="mono">${esc(s.secret)}</p><small>Keep this secret private. Use a time-based (TOTP) account.</small></div>` : ""}<form id="totp-form">${input("code", "Authenticator code", "text")}<div class="form-error"></div><button type="submit">Verify & continue</button></form>`;
  $("#totp-form input").setAttribute("inputmode", "numeric");
  $("#totp-form input").setAttribute("pattern", "[0-9]{6}");
  formBind("#totp-form", async (b) => {
    const r = await api("/auth/verify", b);
    user = r.user;
    await enter();
  });
}
function shell() {
  const admin = user.role === "admin",
    staff = user.role !== "student";
  let nav = [
    ["dashboard", "◫", "Overview"],
    ["courses", "▤", "Courses"],
    ["sessions", "▦", staff ? "Sessions" : "Check in"],
    ["reports", "▥", "Attendance"],
    ["queue", "↻", "Offline queue"],
    ["profile", "○", "My profile"],
  ];
  if (admin)
    nav.splice(4, 0, ["users", "♙", "Users"], ["system", "⚙", "System"]);
  app.innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><span class="brandmark">▦</span> SCAS</div><div class="eyebrow">WORKSPACE</div><nav class="nav">${nav.map(([key, icon, label]) => `<button data-page="${key}" class="${page === key ? "active" : ""}"><span>${icon}</span>${label}</button>`).join("")}</nav><div class="sidebar-foot">SMART CLASSROOM<br><br>Attendance, made simple.<br><br>ENEL3SF · Prototype</div></aside><div class="workspace"><header class="topbar"><span class="status" id="connection">● ${navigator.onLine ? "Connected" : "Offline · changes can be queued"}</span><div class="who"><div class="avatar">${esc(
    user.name
      .split(" ")
      .map((n) => n[0])
      .slice(0, 2)
      .join(""),
  )}</div><div><strong>${esc(user.name)}</strong><small>${esc(user.role)}</small></div><button class="secondary small" id="logout">Sign out</button></div></header><main></main></div></div>`;
  document
    .querySelectorAll("[data-page]")
    .forEach((el) => (el.onclick = () => navigate(el.dataset.page)));
  $("#logout").onclick = async () => {
    if (
      queue().length &&
      !confirm(
        "There are unsynchronized changes on this device. Sign out and keep them for your next sign-in?",
      )
    )
      return;
    try {
      await api("/logout", {});
      user = null;
      page = "dashboard";
      loginScreen();
    } catch (e) {
      toast("Connect to the server to end your session.");
    }
  };
}
function heading(title, sub, actions = "") {
  return `<div class="page-heading"><div><div class="eyebrow">SMART CLASSROOM</div><h1>${title}</h1><p>${sub}</p></div><div class="actions">${actions}</div></div>`;
}
async function enter() {
  shell();
  await refreshData();
  if (pendingToken && user.role === "student") {
    page = "sessions";
    shell();
    await checkinPage();
    try {
      await doCheckin(pendingToken);
    } catch (e) {
      $("#checkin-result").innerHTML =
        `<div class="error">${esc(e.message)}</div>`;
    }
  } else await navigate(page);
}
async function refreshData() {
  const [c, s] = await Promise.all([api("/courses"), api("/sessions")]);
  courseList = c.courses;
  sessionList = s.sessions;
}
async function navigate(target) {
  displayedSessionId = null;
  page = target;
  document
    .querySelectorAll("[data-page]")
    .forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $("main").innerHTML = '<p class="muted">Loading…</p>';
  try {
    if (["dashboard", "courses", "sessions", "reports"].includes(page)) {
      try {
        await refreshData();
      } catch (e) {
        if (!e.network) throw e;
        toast("Showing the information loaded before the connection was lost.");
      }
    }
    await {
      dashboard,
      courses,
      sessions: () =>
        user.role === "student" ? checkinPage() : sessionsPage(),
      reports: reportsPage,
      users: usersPage,
      system: systemPage,
      queue: queuePage,
      profile: profilePage,
    }[page]();
  } catch (e) {
    $("main").innerHTML =
      heading("Unable to load this page", "Your changes have not been lost.") +
      `<div class="error">${esc(e.network ? "Cannot reach the server. Reconnect or open Offline queue." : e.message)}</div><button id="retry">Try again</button>`;
    $("#retry").onclick = () => navigate(page);
  }
}
async function dashboard() {
  const { summary, rows } = await api("/reports");
  const active = sessionList.filter((s) => s.active);
  $("main").innerHTML =
    heading(
      `Welcome back, ${esc(user.name.split(" ")[0])}.`,
      "A clear view of your classroom, all in one place.",
      user.role !== "student"
        ? '<button id="new-session">＋ New session</button>'
        : '<button id="go-checkin">Check in →</button>',
    ) +
    `<div class="stats">${[
      [courseList.length, "Your courses", "Current course enrolments"],
      [active.length, "Live sessions", "Open for attendance"],
      [
        summary.percentage === null ? "—" : summary.percentage + "%",
        "Attendance rate",
        "Completed sessions · late counts as attended",
      ],
      [summary.absent, "Missed records", "Completed sessions only"],
    ]
      .map(
        ([n, t, d]) =>
          `<div class="stat"><label>${t}</label><strong>${n}</strong><small>${d}</small></div>`,
      )
      .join(
        "",
      )}</div><div class="split"><section class="card"><div class="card-head"><h2>Recent sessions</h2><button class="secondary small" id="all-sessions">View all →</button></div>${sessionTable(sessionList.slice(0, 5))}</section><section class="card"><div class="eyebrow">YOUR NEXT STEP</div><h2>${user.role === "student" ? "Show up. Scan. You’re in." : "Ready for your next class?"}</h2><p class="muted">${user.role === "student" ? "Scan the lecturer’s QR code with your phone camera, then sign in. Your attendance is linked to your account automatically." : "Open a session and display its QR code. Students check in with their own accounts, and you can follow the register as it updates."}</p><div class="hint">${queue().length ? queue().length + " changes waiting in your offline queue." : "All your changes are synchronized on this device."}</div><ul class="help-list"><li>Session QR codes expire automatically.</li><li>Lecturers can correct records with a reason.</li><li>Attendance reports are available as CSV or PDF.</li></ul></section></div><section class="card"><div class="card-head"><h2>Latest attendance</h2></div>${recordTable(rows.slice(0, 6))}</section>`;
  $("#new-session")?.addEventListener("click", newSession);
  $("#go-checkin")?.addEventListener("click", () => navigate("sessions"));
  $("#all-sessions").onclick = () => navigate("sessions");
  bindSessionButtons();
}
function sessionTable(rows) {
  return table(
    ["Session", "Course", "Recorded", "Status", ""],
    rows.map((s) => [
      `<strong>${esc(s.title)}</strong><small>${date(s.starts)} · ${esc(s.kind)}</small>`,
      esc(s.code),
      `${s.attended} / ${s.expected}`,
      badge(s.active ? "active" : "closed"),
      user.role !== "student"
        ? `<button class="secondary small" data-session="${s.id}">Open</button>`
        : "",
    ]),
  );
}
function bindSessionButtons() {
  document
    .querySelectorAll("[data-session]")
    .forEach(
      (b) => (b.onclick = () => sessionDetail(Number(b.dataset.session))),
    );
}
function recordTable(rows) {
  return table(
    ["Session", "Student", "Status", "Recorded via"],
    rows.map((r) => [
      `<strong>${esc(r.title)}</strong><small>${esc(r.course)} · ${date(r.starts)}</small>`,
      `${esc(r.name)}<small>${esc(r.username)}</small>`,
      badge(r.status),
      `${esc(r.source || "—")}<small>${esc(r.reason || "")}</small>`,
    ]),
  );
}
async function courses() {
  $("main").innerHTML =
    heading(
      "Your courses",
      "Manage classes and keep the right students connected.",
      user.role !== "student"
        ? '<button id="new-course">＋ Add course</button>'
        : "",
    ) +
    `<div class="grid">${courseList.map((c) => `<section class="card course-card"><span class="course-code">${esc(c.code)}</span><h2>${esc(c.name)}</h2><p class="muted">${esc(c.lecturer)}</p><div class="course-bottom"><small>${c.students} students enrolled</small>${user.role !== "student" ? `<button class="secondary small" data-roster="${c.id}">Manage roster</button>` : `<button class="secondary small" data-course-report="${c.id}">Attendance →</button>`}</div></section>`).join("") || '<p class="empty">No courses yet.</p>'}</div>`;
  $("#new-course")?.addEventListener("click", newCourse);
  document
    .querySelectorAll("[data-roster]")
    .forEach((b) => (b.onclick = () => rosterDialog(Number(b.dataset.roster))));
  document.querySelectorAll("[data-course-report]").forEach(
    (b) =>
      (b.onclick = () => {
        reportQuery = "course_id=" + b.dataset.courseReport;
        navigate("reports");
      }),
  );
}
async function newCourse() {
  let lecturers = [];
  if (user.role === "admin")
    lecturers = (await api("/users")).users
      .filter((u) => u.role === "lecturer" && u.active)
      .map((u) => [u.id, u.name]);
  modal(
    `<h2>Create a course</h2><form id="course-form">${input("code", "Course code")}${input("name", "Course name")}${user.role === "admin" ? select("lecturer_id", "Lecturer", lecturers) : ""}<div class="form-error"></div><button type="submit">Create course</button></form>`,
  );
  formBind("#course-form", async (b) => {
    await api("/courses", b);
    $("#modal").close();
    toast("Course created. Add students to the roster next.");
    await navigate("courses");
  });
}
async function rosterDialog(cid) {
  const r = await api(`/courses/${cid}/roster`);
  modal(
    `<h2>${esc(courseList.find((c) => c.id === cid).code)} · Student roster</h2>${table(
      ["Student", "ID", "Account"],
      r.students.map((s) => [
        esc(s.name),
        esc(s.username),
        s.active ? "Active" : "Inactive",
      ]),
    )}<p><small>Existing session rosters are preserved. New enrolments apply to future sessions.</small></p><form id="roster-form">${input("username", "Add student by username / student number")}<div class="form-error"></div><button type="submit">Enroll student</button></form>`,
  );
  formBind("#roster-form", async (b) => {
    await api(`/courses/${cid}/roster`, b);
    $("#modal").close();
    await refreshData();
    await rosterDialog(cid);
  });
}
async function sessionsPage() {
  $("main").innerHTML =
    heading(
      "Attendance sessions",
      "Create, monitor and correct attendance for your classes.",
      '<button id="new-session">＋ New session</button>',
    ) + `<section class="card">${sessionTable(sessionList)}</section>`;
  $("#new-session").onclick = newSession;
  bindSessionButtons();
}
function newSession() {
  if (!courseList.length) {
    toast("Create a course and enroll students first.");
    return;
  }
  modal(
    `<h2>Start an attendance session</h2><form id="session-form">${select(
      "course_id",
      "Course",
      courseList.map((c) => [c.id, c.code + " · " + c.name]),
    )}${input("title", "Session title")}<div class="form-grid">${select(
      "kind",
      "Session type",
      [
        ["lecture", "Lecture"],
        ["test", "Test"],
        ["exam", "Exam"],
      ],
    )}${input("minutes", "Check-in window (1–240 minutes)", "number", 15)}</div><p><small>Starts immediately. Students who check in more than 10 minutes after the start are marked late.</small></p><div class="form-error"></div><button type="submit">Start session & show QR</button></form>`,
  );
  $("#session-form input[type=number]").min = 1;
  $("#session-form input[type=number]").max = 240;
  formBind("#session-form", async (b) => {
    const r = await api("/sessions", b);
    $("#modal").close();
    page = "sessions";
    await sessionDetail(r.id);
  });
}
async function sessionDetail(sid) {
  displayedSessionId = sid;
  const r = await api(`/sessions/${sid}`);
  currentSession = r;
  const s = r.session;
  $("main").innerHTML =
    heading(
      esc(s.title),
      `${esc(s.kind)} · Started ${date(s.starts)}`,
      `<button class="secondary" id="refresh-session">Refresh register</button>${s.active ? '<button class="danger" id="close-session">End session</button>' : ""}`,
    ) +
    `<div class="split"><section class="card"><div class="card-head"><h2>Class register</h2>${badge(s.active ? "active" : "closed")}</div>${table(
      ["Student", "Status", ""],
      r.students.map((u) => [
        `${esc(u.name)}<small>${esc(u.username)}</small>`,
        badge(u.status),
        `<button class="secondary small" data-correct="${u.id}">Correct</button>`,
      ]),
    )}${r.pending.length ? `<h3>Offline submissions awaiting review</h3>${r.pending.map((p) => `<div class="banner">${esc(p.name)} · Submitted ${date(p.requested_at)}<br><button class="secondary small" data-correct="${p.student_id}">Review & correct</button></div>`).join("")}` : ""}</section><section class="card qr"><div class="eyebrow">SCAN TO CHECK IN</div><h2>${s.active ? "Your classroom is open" : "Session has ended"}</h2>${s.active ? `<img src="/api/sessions/${sid}/qr" alt="Session check-in QR code"><p><small>Valid until ${date(s.expires)}</small></p><a class="qr-url" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a><button class="secondary" id="copy-link">Copy check-in link</button><details><summary>Manual session token</summary><p class="qr-code">${esc(s.token)}</p></details>` : '<p class="muted">This QR code no longer accepts new check-ins. You can still correct the register.</p>'}<p><small>Students use their own account. For phone access, open SCAS using the server’s LAN address.</small></p></section></div>`;
  $("#refresh-session").onclick = () => sessionDetail(sid);
  $("#close-session")?.addEventListener("click", async () => {
    if (
      confirm("End this session? Its QR code will stop accepting check-ins.")
    ) {
      await api(`/sessions/${sid}/close`, {});
      await sessionDetail(sid);
    }
  });
  $("#copy-link")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(r.url);
      toast("Link copied.");
    } catch {
      toast("Select and copy the displayed link.");
    }
  });
  document
    .querySelectorAll("[data-correct]")
    .forEach(
      (b) => (b.onclick = () => correctDialog(sid, Number(b.dataset.correct))),
    );
}
function correctDialog(sid, uid) {
  const s = currentSession.students.find((u) => u.id === uid);
  modal(
    `<h2>Correct attendance</h2><p>${esc(s.name)} · ${esc(s.username)}</p><form id="correct-form">${select(
      "status",
      "Attendance status",
      [
        ["present", "Present"],
        ["late", "Late"],
        ["absent", "Absent"],
        ["excused", "Excused"],
      ],
      s.status,
    )}${input("reason", "Reason for correction", "text", s.reason || "")}<p><small>Corrections are recorded in the audit log. If disconnected, your correction will be queued on this device.</small></p><div class="form-error"></div><button type="submit">Save correction</button></form>`,
  );
  formBind("#correct-form", async (b) => {
    const r = await submitOrQueue(`/sessions/${sid}/attendance`, {
      ...b,
      student_id: uid,
    });
    $("#modal").close();
    if (!r.queued) {
      toast("Attendance updated.");
      await sessionDetail(sid);
    }
  });
}
async function checkinPage() {
  $("main").innerHTML =
    heading(
      "Check in to class",
      "Scan your lecturer’s QR code using your phone camera, or enter the session link.",
    ) +
    `<div class="split"><section class="card"><div class="eyebrow">MARK YOUR ATTENDANCE</div><h2>You’re signed in as ${esc(user.name)}</h2><p class="muted">Paste the QR link or session token below. Your identity is taken from your signed-in account.</p><form id="checkin-form">${input("token", "Session link or token", "text", pendingToken || "")}<div class="form-error"></div><button type="submit">Record my attendance</button></form><div id="checkin-result" class="checkin-result" role="status"></div></section><section class="card"><h2>Before you check in</h2><ul class="help-list"><li>You must be enrolled before the session starts.</li><li>Each student can have only one record per session.</li><li>After 10 minutes, check-in is marked late.</li><li>If you lose connection, your submission is queued here.</li><li>Expired offline submissions need lecturer review.</li></ul></section></div><section class="card"><h2>Your sessions</h2>${sessionTable(sessionList)}</section>`;
  formBind("#checkin-form", (b) => doCheckin(b.token));
}
async function doCheckin(value) {
  let token = value.trim();
  try {
    const url = new URL(token);
    token = url.searchParams.get("token") || token;
  } catch {}
  const r = await submitOrQueue("/checkin", { token });
  $("#checkin-result").innerHTML =
    `<div class="${r.queued || r.status === "pending" ? "hint" : "success"}">${esc(r.message)}</div>`;
  if (!r.queued) {
    pendingToken = null;
    history.replaceState({}, "", location.pathname);
  }
}
async function reportsPage() {
  const result = await api("/reports" + (reportQuery ? "?" + reportQuery : ""));
  const query = new URLSearchParams(reportQuery);
  $("main").innerHTML =
    heading(
      "Attendance history",
      "Filter records, review participation and export your report.",
      '<button class="secondary" id="csv">↓ CSV</button><button id="pdf">↓ PDF</button>',
    ) +
    `<section class="card"><form id="filters" class="filters">${select("course_id", "Course", [["", "All courses"], ...courseList.map((c) => [c.id, c.code])], query.get("course_id"))}${user.role !== "student" ? select("student_id", "Student", [["", "All students"], ...Array.from(new Map(result.rows.map((r) => [r.student_id, [r.student_id, r.name + " · " + r.username]])).values())], query.get("student_id")) : ""}${input("from", "From (UTC)", "date", query.get("from") || "", false)}${input("to", "To (UTC)", "date", query.get("to") || "", false)}<button type="submit">Apply filters</button></form><div class="banner"><strong>${result.summary.percentage === null ? "No completed sessions" : result.summary.percentage + "% attendance"}</strong> · ${result.summary.attended} attended of ${result.summary.total} eligible records. Present and late count as attended; excused and open sessions are excluded.</div>${user.role !== "student" ? '<label class="field"><span>Filter displayed records by student name or ID</span><input id="student-search" placeholder="Search students…"></label>' : ""}<div id="records">${recordTable(result.rows)}</div></section>`;
  formBind("#filters", async (b) => {
    reportQuery = new URLSearchParams(
      Object.entries(b).filter(([k, v]) => v),
    ).toString();
    await reportsPage();
  });
  $("#student-search")?.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    $("#records").innerHTML = recordTable(
      result.rows.filter((r) =>
        (r.name + " " + r.username).toLowerCase().includes(q),
      ),
    );
  });
  $("#csv").onclick = () => downloadReport("csv");
  $("#pdf").onclick = () => downloadReport("pdf");
}
function downloadReport(fmt) {
  window.location.href =
    "/api/reports/export?" +
    (reportQuery ? reportQuery + "&" : "") +
    "format=" +
    fmt;
}
async function usersPage() {
  const { users } = await api("/users");
  $("main").innerHTML =
    heading(
      "User management",
      "Create accounts, maintain profiles and control access.",
      '<button id="add-user">＋ New user</button>',
    ) +
    `<section class="card">${table(
      ["User", "Role", "Account", "2FA", ""],
      users.map((u) => [
        `${esc(u.name)}<small>${esc(u.username)} · ${esc(u.email)}</small>`,
        badge(u.role),
        badge(u.active ? "active" : "inactive"),
        u.two_factor
          ? "Enabled"
          : u.role === "admin"
            ? "Required at sign-in"
            : "Not enabled",
        `<button class="secondary small" data-user="${u.id}">Edit</button>`,
      ]),
    )}</section>`;
  $("#add-user").onclick = () => userDialog();
  document
    .querySelectorAll("[data-user]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          userDialog(users.find((u) => u.id === Number(b.dataset.user)))),
    );
}
function userDialog(u) {
  modal(
    `<h2>${u ? "Edit user" : "Create user"}</h2><form id="user-form">${!u ? input("username", "Username / student number") : ""}${input("name", "Full name", "text", u?.name || "")}${input("email", "Email", "email", u?.email || "", false)}<div class="form-grid">${select(
      "role",
      "Role",
      [
        ["student", "Student"],
        ["lecturer", "Lecturer"],
        ["admin", "Administrator"],
      ],
      u?.role,
    )}${
      u
        ? select(
            "active",
            "Account status",
            [
              [1, "Active"],
              [0, "Inactive"],
            ],
            u.active,
          )
        : ""
    }</div>${input("password", u ? "New password (leave blank to keep)" : "Initial password (10+ characters)", "password", "", !u)}<div class="form-error"></div><button type="submit">${u ? "Save changes" : "Create account"}</button></form>`,
  );
  formBind("#user-form", async (b) => {
    await api(u ? "/users/" + u.id : "/users", b);
    $("#modal").close();
    toast("User saved.");
    await usersPage();
  });
}
async function profilePage() {
  user = (await api("/profile")).user;
  $("main").innerHTML =
    heading("My profile", "Your account details and security settings.") +
    `<div class="split"><section class="card"><h2>Personal information</h2><p><small>${esc(user.username)} · ${esc(user.role)}</small></p><form id="profile-form">${input("name", "Full name", "text", user.name)}${input("email", "Email", "email", user.email, false)}<h3>Change password</h3>${input("current_password", "Current password", "password", "", false)}${input("new_password", "New password (10+ characters)", "password", "", false)}<div class="form-error"></div><button type="submit">Save profile</button></form></section><section class="card"><h2>Two-factor authentication</h2><p class="muted">Use an authenticator app to add a second step to sign-in. It is required for administrators.</p>${user.two_factor ? '<div class="success">Two-factor authentication is enabled.</div>' : `<form id="enable-2fa">${input("password", "Confirm your password", "password")}<div class="form-error"></div><button type="submit">Set up authenticator</button></form>`}</section></div>`;
  formBind("#profile-form", async (b) => {
    await api("/profile", b);
    toast("Profile saved.");
    user = (await api("/profile")).user;
    shell();
    await profilePage();
  });
  if ($("#enable-2fa"))
    formBind("#enable-2fa", async (b) => {
      await api("/profile/2fa", b);
      await twoFactor(true);
    });
}
async function systemPage() {
  const { events } = await api("/audit");
  $("main").innerHTML =
    heading(
      "System & audit",
      "Backup your data and review important changes.",
    ) +
    `<section class="card"><div class="card-head"><div><h2>Database backups</h2><p class="muted">Download a consistent SQLite snapshot including accounts, courses and attendance.</p></div><button id="backup">↓ Download backup</button></div><p><small>Restore from the server using <code>python manage.py restore PATH --confirm</code> while SCAS is stopped. The restore tool validates the backup and saves a copy of the current database first.</small></p></section><section class="card"><h2>Recent audit events</h2>${table(
      ["Time", "Actor", "Action", "Detail"],
      events.map((e) => [
        date(e.created_at),
        esc(e.actor),
        esc(e.action),
        esc(e.detail),
      ]),
    )}</section>`;
  $("#backup").onclick = async () => {
    try {
      const r = await fetch("/api/backup", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
      });
      if (!r.ok) throw new Error((await r.json()).error);
      const blob = await r.blob(),
        url = URL.createObjectURL(blob),
        a = document.createElement("a");
      a.href = url;
      a.download =
        "scas-backup-" + new Date().toISOString().slice(0, 10) + ".sqlite3";
      a.click();
      URL.revokeObjectURL(url);
      toast("Backup downloaded.");
    } catch (e) {
      toast(e.message);
    }
  };
}
async function queuePage() {
  const items = queue();
  $("main").innerHTML =
    heading(
      "Offline queue",
      "Changes saved on this device for your account.",
      '<button id="sync">↻ Synchronize now</button>',
    ) +
    `<section class="card"><div class="banner">${items.length} pending change(s). Expired student check-ins go to lecturer review. A queued change is not yet a confirmed attendance record.</div>${items.map((i) => `<div class="queue-item row"><div><strong>${i.path === "/checkin" ? "Student check-in" : "Lecturer correction"}</strong><small class="muted"> · ${new Date(i.created).toLocaleString()}</small>${i.error ? `<div class="error">${esc(i.error)}</div>` : ""}</div><button class="secondary small" data-discard="${esc(i.id)}">Discard</button></div>`).join("") || '<p class="empty">You’re all caught up.</p>'}<p><small>Keep this browser’s storage until synchronization completes. Sign in again as the same user after a page reload. Offline sign-in is unavailable.</small></p></section>`;
  $("#sync").onclick = syncQueue;
  document.querySelectorAll("[data-discard]").forEach(
    (b) =>
      (b.onclick = () => {
        if (confirm("Discard this queued change?")) {
          saveQueue(queue().filter((i) => i.id !== b.dataset.discard));
          queuePage();
        }
      }),
  );
}
let syncing = false;
async function syncQueue() {
  if (syncing || !user) return;
  syncing = true;
  let done = 0;
  try {
    for (const item of queue()) {
      try {
        await api(item.path, item.body);
        saveQueue(queue().filter((i) => i.id !== item.id));
        done++;
      } catch (e) {
        saveQueue(
          queue().map((i) =>
            i.id === item.id
              ? {
                  ...i,
                  error: e.network
                    ? "Server unavailable. Try again when connected."
                    : e.message,
                }
              : i,
          ),
        );
        if (e.network || e.status === 401) break;
      }
    }
    if (page === "queue") await queuePage();
    toast(
      done
        ? `${done} change(s) synchronized.`
        : "No changes synchronized. Check the queue for details.",
    );
  } finally {
    syncing = false;
  }
}
window.addEventListener("online", () => {
  if ($("#connection")) $("#connection").textContent = "● Connected";
  if (user && queue().length) syncQueue();
});
window.addEventListener("offline", () => {
  if ($("#connection"))
    $("#connection").textContent = "● Offline · changes can be queued";
  toast("Connection lost. Attendance changes can be queued on this device.");
});
window.addEventListener("unhandledrejection", (event) => {
  event.preventDefault();
  toast(event.reason?.message || "Something went wrong. Try again.");
});
(async () => {
  try {
    const r = await api("/bootstrap");
    csrf = r.csrf;
    user = r.user;
    if (user) await enter();
    else loginScreen();
  } catch (e) {
    app.innerHTML =
      '<div class="loading"><h1>SCAS is offline</h1><p>Reconnect to sign in. Previously queued changes remain on this device.</p><button id="reload">Try again</button></div>';
    $("#reload").onclick = () => location.reload();
  }
  if ("serviceWorker" in navigator)
    navigator.serviceWorker.register("/sw.js").catch(() => {});
})();

setInterval(() => {
  if (
    user &&
    displayedSessionId &&
    !document.hidden &&
    !$("#modal").open &&
    navigator.onLine
  )
    sessionDetail(displayedSessionId).catch(() => {});
}, 10000);
