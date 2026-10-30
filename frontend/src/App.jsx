// FDR SENTINEL frontend - one file, small components, grouped by section.
import { useState, useEffect, useCallback } from "react";
import { Sparkles, Copy, Settings as Cog, Home, FileText, Upload, Bell, RefreshCw, History, Clock, CheckCircle, Building2, AlertTriangle, Calendar, Users, LogOut, ShieldCheck, Menu } from "lucide-react";

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
  officer: [["overview", "Overview", Home], ["institutions", "All Institutions", Building2], ["fdrs", "All FDR Records", FileText], ["alerts", "Risk Monitoring", AlertTriangle], ["dups", "Duplicate Detection", Copy], ["expiry", "Expiry Tracker", Calendar], ["requests", "Renewal & Release", RefreshCw], ["notices", "Notices", Bell], ["audit", "Audit History", History]],
  senior: [["overview", "Overview", Home], ["requests", "Escalated & Final Approvals", ShieldCheck], ["notices", "Notices", Bell], ["audit", "Audit History", History]],
  admin: [["overview", "System Overview", Home], ["users", "Users & Roles", Users], ["institutions", "Institutions", Building2], ["audit", "Audit History", History]],
};

Object.values(NAV).forEach((n) => n.push(["settings", "Settings", Cog]));

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
      <div className="brand"><ShieldCheck /> SENTINEL</div><p className="mut">Intelligent Financial Instrument Monitoring & Compliance Platform</p>
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
const COL = { "Bank Confirmed": "#1b8a5a", "Pending Bank Verification": "#d98a1c", "Discrepancy Reported": "#e5604d", Unverified: "#9a9588", Active: "#1b8a5a", Approaching: "#d98a1c", Matured: "#e5604d", Overdue: "#b23a2b", Closed: "#9a9588", High: "#e5604d", Medium: "#d98a1c", Low: "#1b8a5a" };
const Bars = ({ data, color = "#3b6ea5" }) => { const mx = Math.max(1, ...Object.values(data)); return Object.keys(data).length ? Object.entries(data).map(([k, v]) => <div className="bar" key={k}><span>{k}</span><i style={{ width: (v / mx) * 55 + "%", background: COL[k] || color }} /><em>{v}</em></div>) : <Empty />; };
const Cols = ({ data }) => { const mx = Math.max(1, ...Object.values(data)); return <div className="cols">{Object.entries(data).map(([k, v]) => <div key={k}><em>{v}</em><i style={{ height: (v / mx) * 100 + "%" }} /><span>{k}</span></div>)}</div>; };
function Donut({ data, title }) {
  const tot = Object.values(data).reduce((a, b) => a + b, 0), R = 42, C = 2 * Math.PI * R; let off = 0;
  return <div className="card"><h3>{title}</h3><div className="donut"><svg viewBox="0 0 120 120" width="140" height="140"><circle cx="60" cy="60" r={R} fill="none" stroke="#ece6d8" strokeWidth="16" />
    {Object.entries(data).map(([k, v]) => { const len = tot ? (v / tot) * C : 0; const el = <circle key={k} cx="60" cy="60" r={R} fill="none" stroke={COL[k] || "#6d4fc2"} strokeWidth="16" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-off} transform="rotate(-90 60 60)" />; off += len; return el; })}
    <text x="60" y="60" textAnchor="middle" fontSize="20" fontWeight="700" fill="#1f2328">{tot}</text><text x="60" y="73" textAnchor="middle" fontSize="8" fill="#6b6f76">records</text></svg>
    <div>{Object.entries(data).map(([k, v]) => <div key={k} className="lg"><i style={{ background: COL[k] || "#6d4fc2" }} />{k} <b>{v}</b></div>)}</div></div></div>;
}
const Confirm = ({ text, onYes, onNo }) => <div className="modal" style={{ zIndex: 20 }} onClick={onNo}><div className="dlg" onClick={(e) => e.stopPropagation()}><h3>Please confirm</h3><p>{text}</p><div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}><button className="ghost" onClick={onNo}>Cancel</button><button onClick={onYes}>Confirm</button></div></div></div>;
const ACC = (k) => (/confirm/i.test(k) ? "g" : /pending|upcoming/i.test(k) ? "a" : /duplicate|high|matured/i.test(k) ? "r" : "n");
const LINK = { "Total FDRs": "fdrs", "Total institutions": "institutions", "Bank-confirmed": "fdrs", Unverified: "fdrs", "Pending verification": "pending", "Upcoming expiries (30d)": "expiry", "Matured / overdue": "expiry", "Potential duplicates": "dups", "High-priority alerts": "alerts", "Pending renewals": "requests", "Pending releases": "requests" };
function Overview({ user, go, views }) {
  const [d, setD] = useState(null); const [m, setM] = useState(null);
  useEffect(() => { api("/dashboard").then(setD).catch((e) => setM({ type: "err", text: e.message })); }, []);
  if (!d) return m ? <Msg m={m} /> : <Empty t="Loading dashboard…" />;
  const hide = user.role === "institution" ? ["Total institutions", "Pending renewals", "Pending releases"] : user.role === "bank" ? ["Total institutions", "Pending renewals", "Pending releases", "Unverified", "Upcoming expiries (30d)", "Matured / overdue", "High-priority alerts"] : [];
  const c = d.cards, pct = c["Total FDRs"] ? Math.round((c["Bank-confirmed"] / c["Total FDRs"]) * 100) : 0, staff = ["officer", "senior", "admin"].includes(user.role);
  const ins = [c["High-priority alerts"] && `${c["High-priority alerts"]} record(s) carry a high scrutiny priority. Review the listed reasons first.`, c["Potential duplicates"] && `${c["Potential duplicates"]} record(s) resemble existing FDRs. These need human review, not a fraud verdict.`, c["Upcoming expiries (30d)"] && `${c["Upcoming expiries (30d)"]} FDR(s) mature within 30 days. Renewal reminders were generated.`, c["Pending verification"] && `${c["Pending verification"]} record(s) are still waiting for bank confirmation and remain unverified until then.`].filter(Boolean);
  return <>
    <div className="hero"><div><h2>Welcome, {user.name}</h2><p className="mut">Intelligent Financial Instrument Monitoring & Compliance Platform</p></div><div className="prog"><span className="mut">Bank-confirmed</span><div><i style={{ width: pct + "%" }} /></div><b>{pct}%</b></div></div>
    <div className="grid">{Object.entries(c).filter(([k]) => !hide.includes(k)).map(([k, v]) => <div className={"card stat click s-" + ACC(k)} key={k} onClick={() => { const t = k === "Pending verification" && !views.includes("pending") ? "fdrs" : LINK[k]; if (views.includes(t)) go(t); }}><b>{v}</b><span>{k}</span></div>)}</div>
    {staff && ins.length > 0 && <div className="card ai"><h3><Sparkles size={16} /> AI insights <span className="badge b-v">rule-based</span></h3>{ins.map((t) => <p key={t}>• {t}</p>)}</div>}
    <div className="two"><Donut title="Verification status" data={d.by_status} /><Donut title="Expiry status" data={d.by_expiry} /><Donut title="Risk priority (scrutiny, not fraud probability)" data={d.risk_dist} />
      <div className="card"><h3>Monthly submissions</h3><Cols data={d.monthly} /></div>
      {staff && <div className="card"><h3>Institution-wise FDRs</h3><Bars data={d.by_institution} /></div>}
      {d.recent.length > 0 && <div className="card"><h3>Recent activity</h3>{d.recent.map((e) => <p key={e.id}><b>{e.action}</b><br /><span className="mut">{e.user} ({e.role}) · {e.time.replace("T", " ")}</span></p>)}</div>}</div></>;
}

/* ---------- FDR TABLE + DETAIL ---------- */
function Fdrs({ user, mode }) {
  const [rows, setRows] = useState(null); const [q, setQ] = useState(""); const [st, setSt] = useState(""); const [ex, setEx] = useState(""); const [sel, setSel] = useState(null); const [sort, setSort] = useState({ k: "", dir: 1 }); const [pg, setPg] = useState(0);
  const load = useCallback(() => api("/fdrs").then(setRows), []); useEffect(() => { load(); }, [load]); useEffect(() => setPg(0), [q, st, ex, mode]);
  if (!rows) return <Empty t="Loading…" />;
  let r = rows.filter((f) => (!q || (f.fdr_no + f.institution + f.bank).toLowerCase().includes(q.toLowerCase())) && (!st || f.status === st) && (!ex || f.expiry_status === ex));
  if (mode === "pending") r = r.filter((f) => f.status === "Pending Bank Verification");
  if (mode === "done") r = r.filter((f) => f.status !== "Pending Bank Verification");
  if (mode === "dups") r = r.filter((f) => f.duplicates.length);
  if (mode === "alerts") r = r.filter((f) => f.risk.priority !== "Low");
  const key = sort.k || (mode === "alerts" ? "risk" : mode === "expiry" ? "days_left" : ""), dir = sort.k ? sort.dir : mode === "alerts" ? -1 : 1;
  if (key) r = [...r].sort((a, b) => { const x = key === "risk" ? a.risk.score : a[key], y = key === "risk" ? b.risk.score : b[key]; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
  const PS = 8, pages = Math.max(1, Math.ceil(r.length / PS)), view = r.slice(pg * PS, pg * PS + PS);
  const TH = (k, l) => <th className="sort" onClick={() => setSort({ k, dir: sort.k === k ? -sort.dir : 1 })}>{l}{sort.k === k ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</th>;
  const title = { pending: "Pending Bank Verification", done: "Verified / Discrepancy Reports", alerts: "Risk Monitoring", expiry: "Expiry Tracker", dups: "Duplicate Detection" }[mode] || (user.role === "institution" ? "My FDR Records" : "All FDR Records");
  const bk = { Overdue: 0, Matured: 0, "0–7d": 0, "8–15d": 0, "16–30d": 0, "31–60d": 0, "61–90d": 0 };
  if (mode === "expiry") rows.filter((f) => !f.closed).forEach((f) => { const d = f.days_left; const k = d < -30 ? "Overdue" : d < 0 ? "Matured" : d <= 7 ? "0–7d" : d <= 15 ? "8–15d" : d <= 30 ? "16–30d" : d <= 60 ? "31–60d" : d <= 90 ? "61–90d" : null; if (k) bk[k]++; });
  return <><h2>{title}</h2>
    {mode === "alerts" && <div className="msg warn">Risk score shows review priority for officers. It is not a probability of fraud.</div>}
    {mode === "dups" && <div className="msg warn">A duplicate flag means records look similar. It is not a fraud verdict. Open a record to see the reasons, then decide.</div>}
    {mode === "expiry" && <div className="card"><h3>Maturity timeline (live from records)</h3><Cols data={bk} /></div>}
    <div className="tools"><input placeholder="Search FDR no, bank, institution…" value={q} onChange={(e) => setQ(e.target.value)} />
      <select value={st} onChange={(e) => setSt(e.target.value)}><option value="">All statuses</option>{["Pending Bank Verification", "Bank Confirmed", "Discrepancy Reported", "Unverified"].map((s) => <option key={s}>{s}</option>)}</select>
      <select value={ex} onChange={(e) => setEx(e.target.value)}><option value="">All expiry states</option>{["Active", "Approaching", "Matured", "Overdue", "Closed"].map((s) => <option key={s}>{s}</option>)}</select></div>
    <div className="card tw">{r.length === 0 ? <Empty t="No records match these filters." /> : <table><thead><tr>{TH("fdr_no", "FDR no")}{user.role !== "institution" && TH("institution", "Institution")}{TH("bank", "Bank")}{TH("amount", "Amount")}{TH("maturity_date", "Maturity")}{TH("days_left", "Days left")}{TH("expiry_status", "Expiry")}{TH("status", "Status")}{TH("risk", "Risk")}</tr></thead>
      <tbody>{view.map((f) => <tr className="cl" key={f.id} onClick={() => setSel(f.id)}><td><b>{f.fdr_no}</b></td>{user.role !== "institution" && <td>{f.institution}</td>}<td>{f.bank}</td><td>{inr(f.amount)}</td><td>{f.maturity_date}</td><td>{f.days_left}</td><td><Badge t={f.expiry_status} /></td><td><Badge t={f.status} /></td><td><Badge t={f.risk.priority} /></td></tr>)}</tbody></table>}
      {r.length > PS && <div className="pager"><span className="mut">{r.length} records · page {pg + 1}/{pages}</span><span><button className="ghost sm" disabled={pg === 0} onClick={() => setPg(pg - 1)}>Prev</button> <button className="ghost sm" disabled={pg + 1 >= pages} onClick={() => setPg(pg + 1)}>Next</button></span></div>}</div>
    {sel && <Detail id={sel} user={user} onClose={() => { setSel(null); load(); }} />}</>;
}

function Detail({ id, user, onClose }) {
  const [f, setF] = useState(null); const [m, setM] = useState(null); const [conf, setConf] = useState(Object.fromEntries(FIELDS.map(([k]) => [k, true]))); const [rem, setRem] = useState(""); const [rq, setRq] = useState(null); const [ask, setAsk] = useState(null);
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
      <textarea placeholder="Remarks" value={rem} onChange={(e) => setRem(e.target.value)} /><button onClick={() => setAsk({ text: "Submit this SIMULATED bank response? It updates the trust labels and notifies the institution.", fn: () => run(() => api(`/fdrs/${id}/bank`, { method: "POST", body: { confirm: conf, remarks: rem } }), "Verification submitted") })}>Submit response</button></div>}
    {user.role === "institution" && !f.closed && (f.mismatches.length > 0 || f.status === "Discrepancy Reported") && <Correct f={f} onDone={(t) => { setM({ type: "ok", text: t }); load(); }} />}
    {user.role === "institution" && <div className="card"><h3>Requests</h3>{rq ? <><textarea placeholder="Remarks / supporting details" onChange={(e) => setRq({ ...rq, remarks: e.target.value })} />
      {rq.type === "renewal" && <input placeholder="Replacement FDR number (linked to this record)" onChange={(e) => setRq({ ...rq, replacement_fdr_no: e.target.value })} />}
      <button onClick={() => run(() => api("/requests", { method: "POST", body: { ...rq, fdr_id: id } }), "Request submitted")}>Submit {rq.type} request</button></> :
      <><button className="ghost" onClick={() => setRq({ type: "renewal" })}>Request renewal</button> <button className="ghost" onClick={() => setRq({ type: "release" })}>Request release / refund</button></>}</div>}
  {ask && <Confirm text={ask.text} onNo={() => setAsk(null)} onYes={() => { ask.fn(); setAsk(null); }} />}
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
function Notices({ user }) {
  const [n, setN] = useState(null); const [fl, setFl] = useState("All"); const [sel, setSel] = useState(null); const load = () => api("/notices").then(setN); useEffect(() => { load(); }, []);
  if (!n) return <Empty t="Loading…" />;
  const mark = (x) => api(`/notices/${x.id}/read`, { method: "POST" }).then(load);
  const r = n.filter((x) => fl === "All" || (fl === "Unread" ? !x.read : fl === "Expiry" ? x.category === "expiry" : fl === "Verification" ? x.category === "verification" : x.category === "action"));
  return <><div className="hero"><h2>SENTINEL Notices</h2><button className="ghost sm" onClick={() => Promise.all(n.filter((x) => !x.read).map(mark))}>Mark all as read</button></div>
    <div className="tools">{["All", "Unread", "Expiry", "Verification", "Action Required"].map((t) => <button key={t} className={fl === t ? "" : "ghost"} onClick={() => setFl(t)}>{t}{t === "Unread" ? ` (${n.filter((x) => !x.read).length})` : ""}</button>)}</div>
    {r.length === 0 ? <div className="card"><Empty t="No notices in this view." /></div> : r.map((x) => <div key={x.id} className={"card nt n-" + x.category + (x.read ? "" : " unread")}><div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}><b>{x.title}</b><Badge t={x.category === "action" ? "Pending" : x.category === "expiry" ? "Approaching" : "Bank Confirmed"} /></div>
      <p>{x.desc}</p><span className="mut">FDR {x.fdr_no} · {x.time.replace("T", " ")} · {x.read ? "Read" : "Unread"}</span>
      <div style={{ marginTop: 8 }}>{x.fdr_id && <button className="sm" onClick={() => { if (!x.read) mark(x); setSel(x.fdr_id); }}>Open record</button>} {!x.read && <button className="sm ghost" onClick={() => mark(x)}>Mark as read</button>}</div></div>)}
    {sel && <Detail id={sel} user={user} onClose={() => setSel(null)} />}</>;
}

/* ---------- REQUESTS ---------- */
function Requests({ user }) {
  const [r, setR] = useState(null); const [m, setM] = useState(null); const [ask, setAsk] = useState(null); const load = () => api("/requests").then(setR); useEffect(() => { load(); }, []);
  const dec = async (id, decision) => { try { await api(`/requests/${id}/decide`, { method: "POST", body: { decision } }); setM({ type: "ok", text: "Decision recorded and the institution has been notified." }); load(); } catch (e) { setM({ type: "err", text: e.message }); } };
  const confirm = (x, d, t) => setAsk({ text: `${t} this ${x.type} request for FDR ${x.fdr_no}? This is logged in the audit history.`, fn: () => dec(x.id, d) });
  if (!r) return <Empty t="Loading…" />;
  const rows = user.role === "senior" ? r.filter((x) => x.type === "release") : r;
  return <><h2>Renewal, Replacement & Release Requests</h2><Msg m={m} />
    {rows.length === 0 ? <div className="card"><Empty /></div> : rows.map((x) => <div className="card" key={x.id}><div style={{ display: "flex", justifyContent: "space-between" }}><b>{x.type.toUpperCase()} · FDR {x.fdr_no}</b><Badge t={x.status} /></div>
      <p className="mut">{x.institution} · {x.created.replace("T", " ")}{x.replacement_fdr_no ? ` · Linked replacement FDR: ${x.replacement_fdr_no}` : ""}</p><p>{x.remarks}</p>
      {x.checklist && <div><span className="mut">Review checklist (illustrative, not official policy):</span>{x.checklist.map((c) => <div key={c.item}>{c.ok ? "✅" : "⬜"} {c.item}</div>)}</div>}
      {x.decided_by && <p className="mut">Decision by {x.decided_by}</p>}
      {user.role !== "institution" && ["Pending", "Escalated"].includes(x.status) && <p>
        {x.type === "release" && user.role === "officer" && x.status === "Pending" && <button className="sm ghost" onClick={() => confirm(x, "escalate", "Escalate")}>Escalate to senior</button>}{" "}
        {(x.type === "renewal" || user.role === "senior") && <button className="sm green" onClick={() => confirm(x, "approve", "Approve")}>Approve</button>}{" "}<button className="sm red" onClick={() => confirm(x, "reject", "Reject")}>Reject</button></p>}</div>)}
    {ask && <Confirm text={ask.text} onNo={() => setAsk(null)} onYes={() => { ask.fn(); setAsk(null); }} />}</>;
}

/* ---------- EXTRA: CORRECTION + SETTINGS ---------- */
function Correct({ f, onDone }) {
  const [v, setV] = useState(Object.fromEntries(FIELDS.map(([k]) => [k, f[k]]))); const [file, setFile] = useState(null); const [m, setM] = useState(null);
  const send = async () => { const fd = new FormData(); Object.entries(v).forEach(([k, x]) => fd.append(k, x)); if (file) fd.append("file", file); try { await api(`/fdrs/${f.id}/correct`, { method: "POST", form: fd }); onDone("Correction submitted. Checks were re-run and the record is back with the bank."); } catch (e) { setM({ type: "err", text: e.message }); } };
  return <div className="card"><h3>Respond to correction</h3><p className="mut">Fix the entered details and/or upload a corrected document.</p><div className="two">{FIELDS.map(([k, l]) => <div key={k}><label>{l}</label><input type={k === "amount" ? "number" : k.includes("date") ? "date" : "text"} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></div>)}</div>
    <label>Corrected document (optional)</label><input type="file" accept=".pdf,image/*" onChange={(e) => setFile(e.target.files[0])} /><Msg m={m} /><button onClick={send}>Resubmit for verification</button></div>;
}
function Settings({ user }) {
  const perms = { institution: "View and manage only your own FDRs, notices and requests.", bank: "View only verification requests assigned to you.", officer: "Review all submissions, alerts, expiries and requests; escalate releases.", senior: "Review escalated cases and give final release approval.", admin: "Manage users, roles and view system information." };
  return <><h2>Settings</h2><div className="two"><div className="card"><h3>Account</h3><p><b>{user.name}</b><br />{user.email}</p><p className="mut">Role: {user.role}{user.institution ? " · " + user.institution : ""}</p><p>{perms[user.role]}</p></div>
    <div className="card ai"><h3><Sparkles size={16} /> Demo mode & disclaimers</h3><p>• Bank verification is <b>simulated</b> in this prototype.</p><p>• OCR extracts text only. It does not prove a document is genuine.</p><p>• Risk scores show scrutiny priority, not fraud probability.</p><p>• Duplicate flags need human review.</p><p>• Final renewal and release decisions are made by authorized officers.</p></div></div></>;
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
  const page = { overview: <Overview user={user} go={setView} views={nav.map((n) => n[0])} />, dups: <Fdrs user={user} mode="dups" />, settings: <Settings user={user} />, fdrs: <Fdrs user={user} />, pending: <Fdrs user={user} mode="pending" />, done: <Fdrs user={user} mode="done" />, alerts: <Fdrs user={user} mode="alerts" />, expiry: <Fdrs user={user} mode="expiry" />,
    submit: <Submit />, notices: <Notices user={user} />, requests: <Requests user={user} />, audit: <Audit />, users: <UsersView />, institutions: <Institutions /> }[view];
  return <div className="app" data-role={user.role}><aside className={"side" + (open ? " open" : "")}><div className="brand"><ShieldCheck /> SENTINEL</div><div className="tag">Financial Instrument Monitoring</div>
    {nav.map(([k, l, I]) => <a key={k} className={view === k ? "on" : ""} onClick={() => { setView(k); setOpen(false); }}><I size={18} />{l}</a>)}
    <a style={{ marginTop: "auto" }} onClick={() => { sessionStorage.clear(); setUser(null); }}><LogOut size={18} />Log out</a></aside>
    <div className="main"><div className="top"><button className="menu ghost sm" onClick={() => setOpen(!open)}><Menu size={16} /></button><div><b>{user.name}</b> <span className="mut">· {label}{user.institution && user.role === "institution" ? " · " + user.institution : ""}</span></div><span className="demo">DEMO MODE</span></div>
      <div className="content" key={view}>{page}</div></div></div>;
}
