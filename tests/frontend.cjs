/* DOM integration smoke test. Run after starting SCAS with --demo on a disposable DB.
   npm install --no-save jsdom
   SCAS_TEST_URL=http://127.0.0.1:8080 node tests/frontend.cjs
   This verifies HTML/JS behavior, not visual layout or a real browser engine. */
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const base = process.env.SCAS_TEST_URL || "http://127.0.0.1:8080";
const root = path.resolve(__dirname, "..");
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, label) {
  for (let i = 0; i < 150; i++) {
    if (fn()) return;
    await delay(20);
  }
  throw new Error("Timed out: " + label);
}
function makeApp(url = base) {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => errors.push(e.message));
  const dom = new JSDOM(
    fs.readFileSync(path.join(root, "templates/index.html"), "utf8"),
    {
      url,
      runScripts: "outside-only",
      pretendToBeVisual: true,
      virtualConsole,
    },
  );
  const win = dom.window;
  let cookie = "",
    online = true;
  win.fetch = async (url, opts = {}) => {
    if (!online) throw new TypeError("Simulated network failure");
    const res = await fetch(new URL(url, base), {
      ...opts,
      headers: { ...opts.headers, ...(cookie ? { Cookie: cookie } : {}) },
    });
    const c = res.headers.get("set-cookie");
    if (c) cookie = c.split(";")[0];
    return res;
  };
  win.confirm = () => true;
  win.HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  win.HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  win.eval(fs.readFileSync(path.join(root, "static/app.js"), "utf8"));
  const q = (s) => win.document.querySelector(s);
  const click = (s) => {
    assert(q(s), "Missing " + s);
    q(s).click();
  };
  const fill = (s, v) => {
    assert(q(s), "Missing " + s);
    q(s).value = v;
  };
  const submit = (s) =>
    q(s).dispatchEvent(
      new win.Event("submit", { bubbles: true, cancelable: true }),
    );
  return {
    dom,
    win,
    q,
    click,
    fill,
    submit,
    errors,
    setOnline: (v) => {
      online = v;
    },
  };
}
async function login(a, username) {
  await until(() => a.q("#login-form"), "login screen");
  a.fill("[name=username]", username);
  a.fill("[name=password]", "DemoPass123!");
  a.submit("#login-form");
  await until(
    () =>
      (a.q("main") && a.q("main").textContent.includes("Welcome back")) ||
      a.q("#checkin-result")?.textContent.includes("successfully"),
    "signed in " + username,
  );
}
(async () => {
  const l = makeApp();
  await login(l, "lecturer");
  assert(l.q("main").textContent.includes("Attendance rate"));
  l.click("#new-session");
  l.fill("[name=title]", "DOM workflow test");
  l.submit("#session-form");
  await until(() => l.q(".qr-url"), "QR session created");
  const url = l.q(".qr-url").href;
  const token = new URL(url).searchParams.get("token");
  const s = makeApp(url);
  await login(s, "student");
  assert(s.q("#checkin-result").textContent.includes("successfully"));
  s.fill("[name=token]", token);
  s.submit("#checkin-form");
  await until(
    () => s.q("#checkin-result").textContent.includes("already recorded"),
    "duplicate feedback",
  );
  l.click("#refresh-session");
  await until(
    () => l.q("tbody").textContent.includes("present"),
    "live register",
  );
  l.click('[data-correct="3"]');
  l.fill("[name=status]", "late");
  l.fill("[name=reason]", "DOM test correction");
  l.submit("#correct-form");
  await until(
    () => !l.q("#modal").open && l.q("tbody").textContent.includes("late"),
    "manual correction",
  );
  const s2 = makeApp();
  await login(s2, "student2");
  s2.click("[data-page=sessions]");
  await until(() => s2.q("#checkin-form"), "check-in screen");
  s2.fill("[name=token]", token);
  s2.setOnline(false);
  s2.submit("#checkin-form");
  await until(
    () => s2.q("#checkin-result").textContent.includes("Saved on this device"),
    "offline queue save",
  );
  s2.click("[data-page=queue]");
  await until(() => s2.q("#sync"), "queue screen");
  assert(s2.q("main").textContent.includes("1 pending"));
  s2.setOnline(true);
  s2.click("#sync");
  await until(
    () => s2.q("main").textContent.includes("0 pending"),
    "queue synchronization",
  );
  l.click("#close-session");
  await until(
    () => l.q("main").textContent.includes("Session has ended"),
    "closed session",
  );
  s.click("[data-page=reports]");
  await until(() => s.q("#filters"), "reports screen");
  assert(s.q("#records").textContent.includes("DOM workflow test"));
  assert(!s.q("#records").textContent.includes("Sam Mokoena"));
  s.click("[data-page=profile]");
  await until(() => s.q("#profile-form"), "profile");
  s.fill("[name=name]", "Alex DOM");
  s.submit("#profile-form");
  await until(
    () => s.q(".who").textContent.includes("Alex DOM"),
    "profile update",
  );
  const admin = makeApp();
  await until(() => admin.q("#login-form"), "admin sign-in");
  admin.fill("[name=username]", "admin");
  admin.fill("[name=password]", "DemoPass123!");
  admin.submit("#login-form");
  await until(() => admin.q("#totp-form"), "authenticator enrollment");
  const secret = admin.q(".mono").textContent;
  const bits = [...secret]
    .map((c) =>
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        .indexOf(c)
        .toString(2)
        .padStart(5, "0"),
    )
    .join("");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = require("node:crypto")
    .createHmac("sha1", key)
    .update(counter)
    .digest();
  const offset = digest[19] & 15;
  const code = ((digest.readUInt32BE(offset) & 0x7fffffff) % 1000000)
    .toString()
    .padStart(6, "0");
  admin.fill("[name=code]", code);
  admin.submit("#totp-form");
  await until(() => admin.q("[data-page=users]"), "admin dashboard");
  admin.click("[data-page=users]");
  await until(() => admin.q("#add-user"), "users page");
  admin.click("#add-user");
  admin.fill("[name=username]", "dom_user");
  admin.fill("[name=name]", "DOM User");
  admin.fill("[name=password]", "Temporary123!");
  admin.submit("#user-form");
  await until(
    () =>
      !admin.q("#modal").open &&
      admin.q("main").textContent.includes("DOM User"),
    "create user",
  );
  admin.click("[data-page=system]");
  await until(() => admin.q("#backup"), "backup and audit UI");
  assert(admin.q("main").textContent.includes("user.create"));
  for (const a of [l, s, s2, admin]) {
    assert.deepEqual(a.errors, []);
    a.dom.window.close();
  }
  console.log(
    "PASS: lecturer login, session creation, QR link, automatic student capture, duplicate feedback, register refresh, manual correction, offline save/sync, session closure, scoped reports, profile update, admin TOTP enrollment, user creation, audit and backup UI.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
