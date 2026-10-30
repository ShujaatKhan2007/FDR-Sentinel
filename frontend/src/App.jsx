// FDR SENTINEL frontend - one file, small components, grouped by section.
import { useState, useEffect, useCallback } from "react";
import { Home, FileText, Upload, Bell, RefreshCw, History, Clock, CheckCircle, Building2, AlertTriangle, Calendar, Users, LogOut, ShieldCheck, Menu } from "lucide-react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
async function api(path, { method = "GET", body, form } = {}) {
  const h = {}; const t = sessionStorage.getItem("tok"); if (t) h.Authorization = "Bearer " + t;
  if (body) h["Content-Type"] = "application/json";
  const r = await fetch(API + "/api" + path, { method, headers: h, body: form || (body ? JSON.stringify(body) : undefined) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Request failed"); return j;
}
const FIELDS = [["fdr_no", "FDR number"], ["bank", "Bank"], ["amount", "Amount"], ["issue_date", "Issue date"], ["maturity_date", "Maturity date"]];
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN");
const val = (k, v) => (v == null || v === "" ? "—" : k === "amount" ? inr(v) : v);
const tone = { "Bank Confirmed": "g", Active: "g", Low: "g", Approved: "g", "Pending Bank Verification": "a", Pending: "a", Approaching: "a", Medium: "a", "Institution Submitted": "b", Escalated: "b", Discrepancy: "r", "Discrepancy Reported": "r", High: "r", Overdue: "r", Matured: "r", Rejected: "r" };
const Badge = ({ t }) => <span className={"badge b-" + (tone[t] || "x")}>{t}</span>;
const Empty = ({ t = "Nothing to show yet." }) => <div className="empty">{t}</div>;
const Msg = ({ m }) => (m ? <div className={"msg " + m.type}>{m.text}</div> : null);

const NAV = {
  institution: [["overview", "Overview", Home], ["fdrs", "My FDRs", FileText], ["submit", "Submit New FDR", Upload], ["notices", "Notices", Bell], ["requests", "Renewal / Release", RefreshCw], ["audit", "Activity History", History]],
  bank: [["overview", "Overview", Home], ["pending", "Pending Verification", Clock], ["done", "Verified / Discrepancy", CheckCircle], ["audit", "Verification History", History]],
  officer: [["overview", "Overview", Home], ["institutions", "All Institutions", Building2], ["fdrs", "All FDR Records", FileText], ["alerts", "Risk Alerts", AlertTriangle], ["expiry", "Expiry Monitoring", Calendar], ["requests", "Renewal & Release", RefreshCw], ["notices", "Notices", Bell], ["audit", "Audit History", History]],
  senior: [["overview", "Overview", Home], ["requests", "Escalated & Final Approvals", ShieldCheck], ["notices", "Notices", Bell], ["audit", "Audit History", History]],
  admin: [["overview", "System Overview", Home], ["users", "Users & Roles", Users], ["institutions", "Institutions", Building2], ["audit", "Audit History", History]],
};

/* ---------- LOGIN / REGISTER ---------- */
function Login({ onLogin }) {
  const [mode, setMode] = useState("login"); const [f, setF] = useState({ email: "inst@demo.in", password: "Demo@123" }); const [m, setM] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const go = async (e) => {
    e.preventDefault(); setM(null);
    try {
      if (mode === "login") { const r = await api("/login", { method: "POST", body: f }); sessionStorage.setItem("tok", r.token); onLogin(r.user); }
      else if (mode === "register") { await api("/register", { method: "POST", body: f }); setMode("login"); setM({ type: "ok", text: "Registered. Please log in." }); }
      else setM({ type: "ok", text: "Demo: password reset is a UI placeholder. Use Demo@123." });
    } catch (x) { setM({ type: "err", text: x.message }); }
  };
  const demos = [["Institution", "inst@demo.in"], ["Bank", "bank@demo.in"], ["AICTE Officer", "officer@demo.in"], ["Senior Officer", "senior@demo.in"], ["Admin", "admin@demo.in"]];
  return (
    <div className="login"><form className="box" onSubmit={go}>
      <div className="brand"><ShieldCheck /> FDR <span>SENTINEL</span></div><p className="mut">AI-assisted FDR management & monitoring</p>
      {mode === "register" && <><label>Your name</label><input required onChange={set("name")} /><label>Institution name</label><input required onChange={set("institution")} /></>}
      <label>Email</label><input type="email" required value={f.email} onChange={set("email")} />
      {mode !== "forgot" && <><label>Password</label><input type="password" required value={f.password} onChange={set("password")} /></>}
      <Msg m={m} /><button style={{ width: "100%" }}>{mode === "login" ? "Log in" : mode === "register" ? "Register institution" : "Send reset link"}</button>
      <p className="mut" style={{ textAlign: "center" }}>
        <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "login" ? "register" : "login"); }}>{mode === "login" ? "New institution? Register" : "Back to login"}</a>{" · "}
        <a href="#" onClick={(e) => { e.preventDefault(); setMode("forgot"); }}>Forgot password</a></p>
      <div className="demo" style={{ marginTop: 6 }}>DEMO MODE · password for all: Demo@123</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>{demos.map(([n, e]) => <button type="button" className="ghost sm" key={e} onClick={() => setF({ email: e, password: "Demo@123" })}>{n}</button>)}</div>
    </form></div>
  );
}

/* ---------- OVERVIEW ---------- */
const Bars = ({ data }) => { const mx = Math.max(1, ...Object.values(data)); return Object.keys(data).length ? Object.entries(data).map(([k, v]) => <div className="bar" key={k}><span>{k}</span><i style={{ width: (v / mx) * 55 + "%" }} /><em>{v}</em></div>) : <Empty />; };
function Overview({ user }) {
  const [d, setD] = useState(null); const [m, setM] = useState(null);
  useEffect(() => { api("/dashboard").then(setD).catch((e) => setM({ type: "err", text: e.message })); }, []);
  if (!d) return m ? <Msg m={m} /> : <Empty t="Loading dashboard…" />;
  const hide = user.role === "institution" ? ["Total institutions", "Pending renewals", "Pending releases"] : user.role === "bank" ? ["Total institutions", "Pending renewals", "Pending releases", "Unverified", "Upcoming expiries (30d)", "Matured / overdue", "High-priority alerts"] : [];
  return <>
    <h2>Overview</h2><div className="grid">{Object.entries(d.cards).filter(([k]) => !hide.includes(k)).map(([k, v]) => <div className="card stat" key={k}><b>{v}</b><span>{k}</span></div>)}</div>
    <div className="two"><div className="card"><h3>FDRs by verification status</h3><Bars data={d.by_status} /></div><div className="card"><h3>FDRs by expiry status</h3><Bars data={d.by_expiry} /></div>
      {user.role !== "institution" && user.role !== "bank" && <div className="card"><h3>Institution-wise FDRs</h3><Bars data={d.by_institution} /></div>}
      {d.recent.length > 0 && <div className="card"><h3>Recent activity</h3>{d.recent.map((e) => <p key={e.id}><b>{e.action}</b><br /><span className="mut">{e.user} ({e.role}) · {e.time.replace("T", " ")}</span></p>)}</div>}</div></>;
}

/* ---------- FDR TABLE + DETAIL ---------- */
function Fdrs({ user, mode }) {
  const [rows, setRows] = useState(null); const [q, setQ] = useState(""); const [st, setSt] = useState(""); const [ex, setEx] = useState(""); const [sel, setSel] = useState(null);
  const load = useCallback(() => api("/fdrs").then(setRows), []); useEffect(() => { load(); }, [load]);
  if (!rows) return <Empty t="Loading…" />;
  let r = rows.filter((f) => (!q || (f.fdr_no + f.institution + f.bank).toLowerCase().includes(q.toLowerCase())) && (!st || f.status === st) && (!ex || f.expiry_status === ex));
  if (mode === "pending") r = r.filter((f) => f.status === "Pending Bank Verification");
  if (mode === "done") r = r.filter((f) => f.status !== "Pending Bank Verification");
  if (mode === "alerts") r = r.filter((f) => f.risk.priority !== "Low").sort((a, b) => b.risk.score - a.risk.score);
  if (mode === "expiry") r = [...r].sort((a, b) => a.days_left - b.days_left);
  const title = { pending: "Pending Verification", done: "Verified / Discrepancy Reports", alerts: "Risk Alerts (scrutiny priority)", expiry: "Expiry Monitoring" }[mode] || (user.role === "institution" ? "My FDRs" : "All FDR Records");
  return <><h2>{title}</h2>
    {mode === "alerts" && <div className="msg warn">Risk score shows review priority, not the probability of fraud.</div>}
    <div className="tools"><input placeholder="Search FDR no, bank, institution…" value={q} onChange={(e) => setQ(e.target.value)} />
      <select value={st} onChange={(e) => setSt(e.target.value)}><option value="">All statuses</option>{["Pending Bank Verification", "Bank Confirmed", "Discrepancy Reported", "Unverified"].map((s) => <option key={s}>{s}</option>)}</select>
      <select value={ex} onChange={(e) => setEx(e.target.value)}><option value="">All expiry states</option>{["Active", "Approaching", "Matured", "Overdue", "Closed"].map((s) => <option key={s}>{s}</option>)}</select></div>
    <div className="card tw">{r.length === 0 ? <Empty /> : <table><thead><tr><th>FDR no</th>{user.role !== "institution" && <th>Institution</th>}<th>Bank</th><th>Amount</th><th>Maturity</th><th>Days left</th><th>Expiry</th><th>Status</th><th>Risk</th></tr></thead>
      <tbody>{r.map((f) => <tr className="cl" key={f.id} onClick={() => setSel(f.id)}><td><b>{f.fdr_no}</b></td>{user.role !== "institution" && <td>{f.institution}</td>}<td>{f.bank}</td><td>{inr(f.amount)}</td><td>{f.maturity_date}</td><td>{f.days_left}</td><td><Badge t={f.expiry_status} /></td><td><Badge t={f.status} /></td><td><Badge t={f.risk.priority} /></td></tr>)}</tbody></table>}</div>
    {sel && <Detail id={sel} user={user} onClose={() => { setSel(null); load(); }} />}</>;
}

function Detail({ id, user, onClose }) {
  const [f, setF] = useState(null); const [m, setM] = useState(null); const [conf, setConf] = useState(Object.fromEntries(FIELDS.map(([k]) => [k, true]))); const [rem, setRem] = useState(""); const [rq, setRq] = useState(null);
  const load = () => api("/fdrs/" + id).then(setF).catch((e) => setM({ type: "err", text: e.message })); useEffect(() => { load(); }, []);
  const run = async (fn, ok) => { try { await fn(); setM({ type: "ok", text: ok }); setRq(null); load(); } catch (e) { setM({ type: "err", text: e.message }); } };
  if (!f) return <div className="modal"><div><Msg m={m} /><Empty t="Loading…" /></div></div>;
  const bad = (k) => f.mismatches.find((x) => x.field === k);
  return <div className="modal" onClick={onClose}><div onClick={(e) => e.stopPropagation()}>
    <div style={{ display: "flex", justifyContent: "space-between" }}><h2>{f.fdr_no} <Badge t={f.status} /></h2><button className="ghost sm" onClick={onClose}>Close</button></div>
    <p className="mut">{f.institution} · Record {f.id} · SHA-256: {f.file_hash ? f.file_hash.slice(0, 16) + "…" : "no document"}</p><Msg m={m} />
    {f.ocr_source === "demo" && <div className="demo">DEMO DATA: extraction shown is simulated (real OCR runs on image uploads when Tesseract is installed)</div>}
    <div className="tw"><table><thead><tr><th>Field</th><th>Entered</th><th>Extracted from document</th><th>Trust label</th></tr></thead><tbody>
      {FIELDS.map(([k, l]) => <tr key={k} style={bad(k) ? { background: "#fff3f2" } : null}><td>{l}</td><td>{val(k, f[k])}</td><td>{val(k, f.extracted?.[k])}</td><td><Badge t={f.status === "Unverified" || (f.trust[k] === "Institution Submitted" && f.status === "Unverified") ? "Unverified" : f.trust[k]} /></td></tr>)}</tbody></table></div>
    {f.mismatches.map((x, i) => <div className="msg err" key={i}>{x.message}</div>)}
    <p className="mut">Extraction compares text only — it does not prove the FDR is genuine or bank-verified.</p>
    {f.duplicates.length > 0 && <div className="msg warn"><b>Potential duplicate (flagged for review, not a fraud finding)</b>{f.duplicates.map((d) => <div key={d.id}>Existing record <b>{d.fdr_no}</b> ({d.institution}, {d.status}): {d.reasons.join("; ")}</div>)}</div>}
    <div className="card"><h3>Risk: <Badge t={f.risk.priority} /> · score {f.risk.score}</h3>{f.risk.reasons.map((r) => <div key={r}>• {r}</div>)}<p><b>Next action:</b> {f.risk.action}</p><p className="mut">Expiry: {f.expiry_status} ({f.days_left} days)</p></div>
    {f.bank_remarks && <p className="mut">Bank remarks: {f.bank_remarks} — {f.verified_by} <span className="demo">SIMULATED</span></p>}
    {user.role === "bank" && f.status === "Pending Bank Verification" && <div className="card"><h3>Bank verification <span className="demo">PROTOTYPE / DEMO</span></h3>
      {FIELDS.map(([k, l]) => <label key={k} style={{ display: "block" }}><input type="checkbox" style={{ width: "auto", margin: "0 8px 0 0" }} checked={conf[k]} onChange={(e) => setConf({ ...conf, [k]: e.target.checked })} />{l} matches bank records ({val(k, f[k])})</label>)}
      <textarea placeholder="Remarks" value={rem} onChange={(e) => setRem(e.target.value)} /><button onClick={() => run(() => api(`/fdrs/${id}/bank`, { method: "POST", body: { confirm: conf, remarks: rem } }), "Verification submitted")}>Submit response</button></div>}
    {user.role === "institution" && <div className="card"><h3>Requests</h3>{rq ? <><textarea placeholder="Remarks / supporting details" onChange={(e) => setRq({ ...rq, remarks: e.target.value })} />
      {rq.type === "renewal" && <input placeholder="Replacement FDR number (linked to this record)" onChange={(e) => setRq({ ...rq, replacement_fdr_no: e.target.value })} />}
      <button onClick={() => run(() => api("/requests", { method: "POST", body: { ...rq, fdr_id: id } }), "Request submitted")}>Submit {rq.type} request</button></> :
      <><button className="ghost" onClick={() => setRq({ type: "renewal" })}>Request renewal</button> <button className="ghost" onClick={() => setRq({ type: "release" })}>Request release / refund</button></>}</div>}
  </div></div>;
}

/* ---------- SUBMIT ---------- */
function Submit({ go }) {
  const [f, setF] = useState({ fdr_no: "", bank: "State Bank of India", amount: "", issue_date: "", maturity_date: "" }); const [file, setFile] = useState(null); const [m, setM] = useState(null); const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const sub = async (e) => { e.preventDefault(); setBusy(true); setM(null); const fd = new FormData(); Object.entries(f).forEach(([k, v]) => fd.append(k, v)); if (file) fd.append("file", file);
    try { const r = await api("/fdrs", { method: "POST", form: fd }); const w = r.mismatches.length + r.duplicates.length; setM({ type: w ? "warn" : "ok", text: `Submitted. ${r.mismatches.length} mismatch(es), ${r.duplicates.length} duplicate flag(s). Open “My FDRs” to review.` }); }
    catch (x) { setM({ type: "err", text: x.message }); } setBusy(false); };
  return <><h2>Submit New FDR</h2><form className="card" onSubmit={sub} style={{ maxWidth: 560 }}>
    <label>FDR number</label><input required value={f.fdr_no} onChange={set("fdr_no")} /><label>Issuing bank</label><select value={f.bank} onChange={set("bank")}><option>State Bank of India</option><option>HDFC Bank</option></select>
    <label>Amount (₹)</label><input required type="number" min="1" value={f.amount} onChange={set("amount")} /><label>Issue date</label><input required type="date" value={f.issue_date} onChange={set("issue_date")} />
    <label>Maturity date</label><input required type="date" value={f.maturity_date} onChange={set("maturity_date")} /><label>FDR document (PDF/image) — tip: add “mismatch” to the file name to demo a mismatch</label><input type="file" accept=".pdf,image/*" onChange={(e) => setFile(e.target.files[0])} />
    <Msg m={m} /><button disabled={busy}>{busy ? "Checking…" : "Submit & run checks"}</button></form></>;
}

/* ---------- NOTICES ---------- */
function Notices() {
  const [n, setN] = useState(null); const [fl, setFl] = useState("All"); const load = () => api("/notices").then(setN); useEffect(() => { load(); }, []);
  if (!n) return <Empty t="Loading…" />;
  const r = n.filter((x) => fl === "All" || (fl === "Unread" ? !x.read : fl === "Expiry" ? x.category === "expiry" : fl === "Verification" ? x.category === "verification" : x.category === "action"));
  return <><h2>Notices</h2><div className="tools">{["All", "Unread", "Expiry", "Verification", "Action Required"].map((t) => <button key={t} className={fl === t ? "" : "ghost"} onClick={() => setFl(t)}>{t}</button>)}</div>
    {r.length === 0 ? <div className="card"><Empty t="No notices in this view." /></div> : r.map((x) => <div key={x.id} className={"card " + (x.read ? "" : "unread")}><div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}><b>{x.title}</b><span><Badge t={x.category === "action" ? "Pending" : x.category === "expiry" ? "Approaching" : "Bank Confirmed"} /> <span className="mut">{x.category}</span></span></div>
      <p>{x.desc}</p><span className="mut">FDR {x.fdr_no} · {x.time.replace("T", " ")} · {x.read ? "Read" : "Unread"}</span> {!x.read && <button className="sm ghost" style={{ marginLeft: 8 }} onClick={() => api(`/notices/${x.id}/read`, { method: "POST" }).then(load)}>Mark as read</button>}</div>)}</>;
}

/* ---------- REQUESTS ---------- */
function Requests({ user }) {
  const [r, setR] = useState(null); const [m, setM] = useState(null); const load = () => api("/requests").then(setR); useEffect(() => { load(); }, []);
  const dec = async (id, decision) => { try { await api(`/requests/${id}/decide`, { method: "POST", body: { decision } }); setM({ type: "ok", text: "Decision recorded." }); load(); } catch (e) { setM({ type: "err", text: e.message }); } };
  if (!r) return <Empty t="Loading…" />;
  const rows = user.role === "senior" ? r.filter((x) => x.type === "release") : r;
  return <><h2>{user.role === "institution" ? "Renewal & Release Requests" : "Renewal & Release Requests"}</h2><Msg m={m} />
    {rows.length === 0 ? <div className="card"><Empty /></div> : rows.map((x) => <div className="card" key={x.id}><div style={{ display: "flex", justifyContent: "space-between" }}><b>{x.type.toUpperCase()} · FDR {x.fdr_no}</b><Badge t={x.status} /></div>
      <p className="mut">{x.institution} · {x.created.replace("T", " ")}{x.replacement_fdr_no ? ` · Replacement FDR: ${x.replacement_fdr_no}` : ""}</p><p>{x.remarks}</p>
      {x.checklist && <div><span className="mut">Review checklist (illustrative, not official policy):</span>{x.checklist.map((c) => <div key={c.item}>{c.ok ? "✅" : "⬜"} {c.item}</div>)}</div>}
      {user.role !== "institution" && ["Pending", "Escalated"].includes(x.status) && <p>
        {x.type === "release" && user.role === "officer" && x.status === "Pending" && <button className="sm ghost" onClick={() => dec(x.id, "escalate")}>Escalate to senior</button>}{" "}
        {(x.type === "renewal" || user.role === "senior") && <button className="sm green" onClick={() => dec(x.id, "approve")}>Approve</button>}{" "}<button className="sm red" onClick={() => dec(x.id, "reject")}>Reject</button></p>}</div>)}</>;
}

/* ---------- AUDIT / USERS / INSTITUTIONS ---------- */
function Audit() {
  const [a, setA] = useState(null); useEffect(() => { api("/audit").then(setA); }, []); if (!a) return <Empty t="Loading…" />;
  return <><h2>Audit History</h2><div className={"msg " + (a.chain_valid ? "ok" : "err")}>{a.chain_valid ? "Hash chain intact: no historical entries altered." : "Warning: audit chain broken — entries may have been modified."}</div>
    <div className="card tw">{a.rows.length === 0 ? <Empty /> : <table><thead><tr><th>Time</th><th>User</th><th>Role</th><th>FDR</th><th>Action</th><th>Hash</th></tr></thead><tbody>{a.rows.map((e) => <tr key={e.id}><td>{e.time.replace("T", " ")}</td><td>{e.user}</td><td>{e.role}</td><td>{e.fdr_id || "—"}</td><td>{e.action}</td><td className="mut">{e.hash.slice(0, 10)}…</td></tr>)}</tbody></table>}</div></>;
}
function UsersView() {
  const [u, setU] = useState(null); const load = () => api("/users").then(setU); useEffect(() => { load(); }, []); if (!u) return <Empty t="Loading…" />;
  return <><h2>Users & Roles</h2><div className="card tw"><table><thead><tr><th>Name</th><th>Email</th><th>Institution</th><th>Role</th></tr></thead><tbody>{u.map((x) => <tr key={x.id}><td>{x.name}</td><td>{x.email}</td><td>{x.institution || "—"}</td><td><select style={{ margin: 0 }} value={x.role} onChange={(e) => api(`/users/${x.id}/role`, { method: "POST", body: { role: e.target.value } }).then(load)}>{["institution", "bank", "officer", "senior", "admin"].map((r) => <option key={r}>{r}</option>)}</select></td></tr>)}</tbody></table></div></>;
}
function Institutions() {
  const [d, setD] = useState(null); useEffect(() => { api("/dashboard").then(setD); }, []); if (!d) return <Empty t="Loading…" />;
  return <><h2>Institutions</h2><div className="card"><Bars data={d.by_institution} /></div></>;
}

/* ---------- SHELL ---------- */
export default function App() {
  const [user, setUser] = useState(null); const [view, setView] = useState("overview"); const [open, setOpen] = useState(false);
  useEffect(() => { if (sessionStorage.getItem("tok")) api("/dashboard").then(() => setUser(JSON.parse(sessionStorage.getItem("usr")))).catch(() => sessionStorage.clear()); }, []);
  const login = (u) => { sessionStorage.setItem("usr", JSON.stringify(u)); setUser(u); setView("overview"); };
  if (!user) return <Login onLogin={login} />;
  const nav = NAV[user.role]; const label = { institution: "Institution", bank: "Bank Representative", officer: "AICTE Officer", senior: "Senior Officer", admin: "Administrator" }[user.role];
  const page = { overview: <Overview user={user} />, fdrs: <Fdrs user={user} />, pending: <Fdrs user={user} mode="pending" />, done: <Fdrs user={user} mode="done" />, alerts: <Fdrs user={user} mode="alerts" />, expiry: <Fdrs user={user} mode="expiry" />,
    submit: <Submit />, notices: <Notices />, requests: <Requests user={user} />, audit: <Audit />, users: <UsersView />, institutions: <Institutions /> }[view];
  return <div className="app"><aside className={"side" + (open ? " open" : "")}><div className="brand"><ShieldCheck /> FDR SENTINEL</div>
    {nav.map(([k, l, I]) => <a key={k} className={view === k ? "on" : ""} onClick={() => { setView(k); setOpen(false); }}><I size={18} />{l}</a>)}
    <a style={{ marginTop: "auto" }} onClick={() => { sessionStorage.clear(); setUser(null); }}><LogOut size={18} />Log out</a></aside>
    <div className="main"><div className="top"><button className="menu ghost sm" onClick={() => setOpen(!open)}><Menu size={16} /></button><div><b>{user.name}</b> <span className="mut">· {label}{user.institution && user.role === "institution" ? " · " + user.institution : ""}</span></div><span className="demo">DEMO MODE</span></div>
      <div className="content" key={view}>{page}</div></div></div>;
}
