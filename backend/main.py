"""FDR SENTINEL backend (FastAPI + MongoDB). Single file, grouped by section for beginners."""
import os, io, re, json, uuid, hashlib, datetime as dt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import jwt
load_dotenv()
db = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))[os.getenv("DB_NAME", "fdr_sentinel")]
SECRET = os.getenv("JWT_SECRET", "dev-secret")
app = FastAPI(title="FDR SENTINEL")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

FIELDS = ["fdr_no", "bank", "amount", "issue_date", "maturity_date"]
LBL = {"fdr_no": "FDR number", "bank": "Bank name", "amount": "Amount", "issue_date": "Issue date", "maturity_date": "Maturity date"}
BANKS = ["State Bank of India", "HDFC Bank"]
uid = lambda p: f"{p}-{uuid.uuid4().hex[:6].upper()}"
today = lambda: dt.date.today()
now = lambda: dt.datetime.now().isoformat(timespec="seconds")
def ser(d):
    if d and "_id" in d: d["id"] = d.pop("_id")
    return d
def pw(p): return hashlib.pbkdf2_hmac("sha256", p.encode(), b"sentinel-demo", 1000).hex()  # demo-grade hashing

# ---------- AUTH ----------
def auth(*roles):
    def dep(authorization: str = Header(None)):
        try: p = jwt.decode((authorization or "").replace("Bearer ", ""), SECRET, algorithms=["HS256"])
        except Exception: raise HTTPException(401, "Session expired. Please log in again.")
        u = db.users.find_one({"_id": p["sub"]})
        if not u: raise HTTPException(401, "User not found")
        if roles and u["role"] not in roles: raise HTTPException(403, "Not allowed for your role")
        return u
    return dep

@app.post("/api/login")
def login(b: dict):
    u = db.users.find_one({"email": str(b.get("email", "")).lower()})
    if not u or u["password"] != pw(str(b.get("password", ""))): raise HTTPException(401, "Invalid email or password")
    tok = jwt.encode({"sub": u["_id"], "exp": dt.datetime.utcnow() + dt.timedelta(hours=12)}, SECRET, algorithm="HS256")
    return {"token": tok, "user": {k: u[k] for k in ("name", "email", "role", "institution", "bank")}}

@app.post("/api/register")
def register(b: dict):
    """Institution onboarding."""
    if not all(b.get(k) for k in ("name", "email", "password", "institution")): raise HTTPException(400, "All fields are required")
    if len(b["password"]) < 6: raise HTTPException(400, "Password must be at least 6 characters")
    if db.users.find_one({"email": b["email"].lower()}): raise HTTPException(400, "Email already registered")
    db.users.insert_one({"_id": uid("USR"), "name": b["name"], "email": b["email"].lower(), "password": pw(b["password"]), "role": "institution", "institution": b["institution"]})
    return {"ok": True}

# ---------- AUDIT (hash-linked) ----------
def audit(user, fid, action, old=None, new=None):
    last = db.audit.find_one(sort=[("seq", -1)]) or {}
    e = {"_id": uid("AUD"), "seq": last.get("seq", 0) + 1, "user": user["name"], "role": user["role"], "fdr_id": fid, "action": action, "old": old, "new": new, "time": now(), "prev": last.get("hash", "GENESIS")}
    e["hash"] = hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest()
    db.audit.insert_one(e)

@app.get("/api/audit")
def get_audit(u=Depends(auth())):
    q = {}
    if u["role"] == "institution": q = {"fdr_id": {"$in": [f["_id"] for f in db.fdrs.find({"institution": u["institution"]})]}}
    if u["role"] == "bank": q = {"role": "bank"}
    rows = [ser(e) for e in db.audit.find(q).sort("seq", -1).limit(200)]
    chain = list(db.audit.find().sort("seq", 1)); ok = True; prev = "GENESIS"
    for e in chain:  # recompute every hash to detect tampering
        h = e.pop("hash")
        if e["prev"] != prev or hashlib.sha256(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest() != h: ok = False
        prev = h
    return {"rows": rows, "chain_valid": ok}

# ---------- NOTICES ----------
def notice(inst, fdr_no, title, cat, desc, key=None):
    """cat: expiry | verification | action. 'key' prevents duplicate notices per FDR + milestone."""
    if key and db.notices.find_one({"inst": inst, "key": key}): return
    db.notices.insert_one({"_id": uid("NTC"), "inst": inst, "fdr_no": fdr_no, "title": title, "category": cat, "desc": desc, "time": now(), "read": False, "key": key})

@app.get("/api/notices")
def notices(u=Depends(auth("institution", "officer", "senior"))):
    inst = u["institution"] if u["role"] == "institution" else "AICTE"
    return [ser(n) for n in db.notices.find({"inst": inst}).sort("time", -1)]
@app.post("/api/notices/{nid}/read")
def read_notice(nid: str, u=Depends(auth())):
    db.notices.update_one({"_id": nid}, {"$set": {"read": True}}); return {"ok": True}

# ---------- OCR, COMPARISON, DUPLICATES, RISK ----------
def run_ocr(data, filename, e):
    """Real OCR via Tesseract for images. Anything else falls back to clearly-labelled DEMO data."""
    try:
        import pytesseract; from PIL import Image
        t = pytesseract.image_to_string(Image.open(io.BytesIO(data)))
        x = {}
        m = re.search(r"(?:FDR|Receipt)\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z0-9\-/]{5,})", t, re.I); x["fdr_no"] = m.group(1) if m else None
        m = re.search(r"(?:Rs\.?|₹|INR)\s*([\d,]+)", t); x["amount"] = float(m.group(1).replace(",", "")) if m else None
        x["bank"] = next((b for b in BANKS if b.lower() in t.lower()), None)
        ds = re.findall(r"\d{4}-\d{2}-\d{2}", t); x["issue_date"], x["maturity_date"] = (ds + [None, None])[:2]
        return x, "tesseract"
    except Exception:
        x = dict(e)  # DEMO: pretend extraction. Put 'mismatch' in the file name to simulate a wrong amount.
        if "mismatch" in filename.lower(): x["amount"] = round(e["amount"] * 1.2)
        return x, "demo"

def same(k, a, b):
    if k == "amount": return float(a) == float(b)
    if k == "bank": return str(a).lower() in str(b).lower() or str(b).lower() in str(a).lower()
    return re.sub(r"\W", "", str(a)).upper() == re.sub(r"\W", "", str(b)).upper()

def compare(e, x):
    out = []
    for k in FIELDS:
        if not x.get(k): out.append({"field": k, "type": "missing", "message": f"{LBL[k]} could not be read from the document."})
        elif not same(k, e[k], x[k]): out.append({"field": k, "type": "mismatch", "message": f"{LBL[k]} mismatch: entered {e[k]}, document shows {x[k]}. Please check and upload a correct document or fix the entry."})
    if x.get("issue_date") and x.get("maturity_date") and x["maturity_date"] <= x["issue_date"]:
        out.append({"field": "maturity_date", "type": "invalid", "message": "Document shows maturity date on/before issue date."})
    return out

def find_dups(e, h, exclude=None):
    out = []
    for o in db.fdrs.find({"_id": {"$ne": exclude}}):
        why = []
        if h and o.get("file_hash") == h: why.append("Identical file (same SHA-256 fingerprint)")
        if o["fdr_no"].upper() == e["fdr_no"].upper(): why.append("Same FDR number")
        if o["bank"] == e["bank"] and o["amount"] == e["amount"] and o["maturity_date"] == e["maturity_date"]: why.append("Same bank, amount and maturity date")
        if why: out.append({"id": o["_id"], "fdr_no": o["fdr_no"], "institution": o["institution"], "status": o["status"], "reasons": why})
    return out

def days_left(m): return (dt.date.fromisoformat(m) - today()).days
def exp_status(d, f):
    if f.get("closed"): return "Closed"
    return "Active" if d > 30 else "Approaching" if d >= 0 else "Matured" if d >= -30 else "Overdue"

def risk(f, d):
    """Simple explainable rules. The score is SCRUTINY PRIORITY, not a probability of fraud."""
    s, r = 0, []
    def add(p, t):
        nonlocal s; s += p; r.append(t)
    if f.get("mismatches"): add(30, "Entered and document values do not match")
    if f.get("duplicates"): add(25, "Potential duplicate indicators")
    if not f.get("file_hash"): add(15, "Supporting document missing")
    if f["status"] == "Pending Bank Verification": add(15, "Bank verification pending")
    if f["status"] == "Discrepancy Reported": add(20, "Bank discrepancy unresolved")
    if not f.get("closed") and d <= 30: add(10 if d >= 0 else 15, "Maturity approaching" if d >= 0 else "FDR is past maturity")
    pri = "High" if s >= 50 else "Medium" if s >= 25 else "Low"
    act = {"High": "Escalate to senior officer and contact the institution.", "Medium": "Follow up on the listed items.", "Low": "Routine monitoring."}[pri]
    return {"score": s, "priority": pri, "reasons": r, "action": act}

def enrich(f):
    d = days_left(f["maturity_date"]); f["days_left"] = d; f["expiry_status"] = exp_status(d, f); f["risk"] = risk(f, d); return ser(f)

def build(inst, e, h, fname, x, src):
    mism = compare(e, x) if src != "none" else []
    dups = find_dups(e, h)
    return {"_id": uid("FDR"), "institution": inst, **e, "file_hash": h, "file_name": fname, "extracted": x, "ocr_source": src, "mismatches": mism, "duplicates": dups,
            "status": "Pending Bank Verification", "trust": {k: "Institution Submitted" for k in FIELDS}, "created": now(), "closed": False}

def assign_bank(f):
    b = db.users.find_one({"role": "bank", "bank": f["bank"]}) or db.users.find_one({"role": "bank"})
    f["bank_user"] = b["_id"] if b else None

# ---------- FDR ENDPOINTS ----------
@app.get("/api/fdrs")
def list_fdrs(u=Depends(auth())):
    q = {"institution": u["institution"]} if u["role"] == "institution" else {"bank_user": u["_id"]} if u["role"] == "bank" else {}
    return [enrich(f) for f in db.fdrs.find(q)]

@app.get("/api/fdrs/{fid}")
def one_fdr(fid: str, u=Depends(auth())):
    f = db.fdrs.find_one({"_id": fid})
    if not f or (u["role"] == "institution" and f["institution"] != u["institution"]) or (u["role"] == "bank" and f.get("bank_user") != u["_id"]): raise HTTPException(404, "Record not found")
    f = enrich(f); f["checklist"] = checklist(f); return f

@app.post("/api/fdrs")
async def add_fdr(fdr_no: str = Form(...), bank: str = Form(...), amount: float = Form(...), issue_date: str = Form(...), maturity_date: str = Form(...), file: UploadFile = File(None), u=Depends(auth("institution"))):
    try: i, m = dt.date.fromisoformat(issue_date), dt.date.fromisoformat(maturity_date)
    except ValueError: raise HTTPException(400, "Dates must be YYYY-MM-DD")
    if amount <= 0 or m <= i: raise HTTPException(400, "Amount must be positive and maturity must be after issue date")
    e = {"fdr_no": fdr_no.strip(), "bank": bank, "amount": amount, "issue_date": issue_date, "maturity_date": maturity_date}
    data = await file.read() if file else b""
    h = hashlib.sha256(data).hexdigest() if data else None
    x, src = run_ocr(data, file.filename, e) if data else ({}, "none")
    f = build(u["institution"], e, h, file.filename if file else None, x, src); assign_bank(f)
    db.fdrs.insert_one(f)
    audit(u, f["_id"], "FDR submitted", None, e)
    if f["mismatches"]: notice(u["institution"], fdr_no, "Document correction required", "action", "; ".join(m["message"] for m in f["mismatches"]))
    if f["duplicates"]:
        notice(u["institution"], fdr_no, "Potential duplicate detected", "action", "This record resembles an existing one and is flagged for officer review (not a fraud finding).")
        notice("AICTE", fdr_no, "Potential duplicate flagged", "action", f"{u['institution']} submitted {fdr_no}; matches existing record(s).")
    if risk(f, days_left(maturity_date))["priority"] == "High": notice("AICTE", fdr_no, "High-priority alert", "action", f"{fdr_no} from {u['institution']} needs scrutiny.")
    return enrich(f)

@app.post("/api/fdrs/{fid}/bank")
def bank_verify(fid: str, b: dict, u=Depends(auth("bank"))):
    """SIMULATED bank verification (prototype only - no real bank integration)."""
    f = db.fdrs.find_one({"_id": fid, "bank_user": u["_id"]})
    if not f: raise HTTPException(404, "Not assigned to you")
    conf = b.get("confirm", {})
    trust = {k: ("Bank Confirmed" if conf.get(k) else "Discrepancy") for k in FIELDS}
    status = "Bank Confirmed" if all(conf.get(k) for k in FIELDS) else "Discrepancy Reported"
    upd = {"trust": trust, "status": status, "bank_remarks": b.get("remarks", ""), "verified_by": u["name"], "verified_at": now(), "simulated": True}
    audit(u, fid, "Bank verification (simulated)", {"status": f["status"], "trust": f["trust"]}, {"status": status, "trust": trust})
    db.fdrs.update_one({"_id": fid}, {"$set": upd})
    if status == "Bank Confirmed": notice(f["institution"], f["fdr_no"], "Bank verification completed", "verification", "All fields confirmed (prototype/demo verification).")
    else: notice(f["institution"], f["fdr_no"], "Bank discrepancy reported", "action", f"Remarks: {b.get('remarks') or 'see record'}")
    return {"status": status}

# ---------- RENEWAL / RELEASE ----------
def checklist(f):  # ILLUSTRATIVE criteria only - not official AICTE policy
    return [{"item": "Bank confirmation for all fields", "ok": f["status"] == "Bank Confirmed"}, {"item": "No unresolved discrepancy", "ok": f["status"] != "Discrepancy Reported"},
            {"item": "No potential-duplicate flag", "ok": not f.get("duplicates")}, {"item": "FDR has reached maturity", "ok": days_left(f["maturity_date"]) <= 0}]

def make_request(u, f, typ, remarks, new_no=None):
    r = {"_id": uid("REQ"), "fdr_id": f["_id"], "fdr_no": f["fdr_no"], "institution": f["institution"], "type": typ, "remarks": remarks, "replacement_fdr_no": new_no, "status": "Pending", "created": now(), "checklist": checklist(f) if typ == "release" else None}
    db.requests.insert_one(r); audit(u, f["_id"], f"{typ.title()} request submitted", None, {"remarks": remarks, "replacement": new_no})
    notice("AICTE", f["fdr_no"], f"{typ.title()} request pending", "action", f"{f['institution']} submitted a {typ} request."); return r

@app.post("/api/requests")
def new_request(b: dict, u=Depends(auth("institution"))):
    f = db.fdrs.find_one({"_id": b.get("fdr_id"), "institution": u["institution"]})
    if not f or b.get("type") not in ("renewal", "release"): raise HTTPException(400, "Invalid request")
    return ser(make_request(u, f, b["type"], b.get("remarks", ""), b.get("replacement_fdr_no")))

@app.get("/api/requests")
def list_requests(u=Depends(auth("institution", "officer", "senior"))):
    q = {"institution": u["institution"]} if u["role"] == "institution" else {}
    return [ser(r) for r in db.requests.find(q).sort("created", -1)]

@app.post("/api/requests/{rid}/decide")
def decide(rid: str, b: dict, u=Depends(auth("officer", "senior"))):
    r = db.requests.find_one({"_id": rid}); d = b.get("decision")
    if not r or d not in ("approve", "reject", "escalate"): raise HTTPException(400, "Invalid decision")
    if r["type"] == "release" and d == "approve" and u["role"] != "senior": raise HTTPException(403, "Only a senior officer can give final approval of a release")
    if d == "escalate" and r["type"] != "release": raise HTTPException(400, "Only release requests are escalated")
    st = {"approve": "Approved", "reject": "Rejected", "escalate": "Escalated"}[d]
    db.requests.update_one({"_id": rid}, {"$set": {"status": st, "decided_by": u["name"], "decision_remarks": b.get("remarks", "")}})
    if d == "approve": db.fdrs.update_one({"_id": r["fdr_id"]}, {"$set": {"closed": True}})
    audit(u, r["fdr_id"], f"{r['type'].title()} request {st.lower()}", {"status": r["status"]}, {"status": st})
    notice(r["institution"], r["fdr_no"], f"{r['type'].title()} status updated", "action" if d != "approve" else "verification", f"Your {r['type']} request is now: {st}.")
    return {"status": st}

# ---------- DASHBOARD / ADMIN ----------
@app.get("/api/dashboard")
def dashboard(u=Depends(auth())):
    fs = list_fdrs(u); c = lambda p: sum(1 for f in fs if p(f))
    reqs = list(db.requests.find({} if u["role"] != "institution" else {"institution": u["institution"]}))
    inst = {}
    for f in fs: inst[f["institution"]] = inst.get(f["institution"], 0) + 1
    by = lambda k: {v: c(lambda f: f[k] == v) for v in sorted({f[k] for f in fs})}
    return {"cards": {"Total institutions": len(inst), "Total FDRs": len(fs), "Bank-confirmed": c(lambda f: f["status"] == "Bank Confirmed"), "Unverified": c(lambda f: f["status"] == "Unverified"),
        "Pending verification": c(lambda f: f["status"] == "Pending Bank Verification"), "Upcoming expiries (30d)": c(lambda f: f["expiry_status"] == "Approaching"),
        "Matured / overdue": c(lambda f: f["expiry_status"] in ("Matured", "Overdue")), "Potential duplicates": c(lambda f: f["duplicates"]),
        "High-priority alerts": c(lambda f: f["risk"]["priority"] == "High"), "Pending renewals": sum(1 for r in reqs if r["type"] == "renewal" and r["status"] == "Pending"),
        "Pending releases": sum(1 for r in reqs if r["type"] == "release" and r["status"] in ("Pending", "Escalated"))},
        "by_status": by("status"), "by_expiry": by("expiry_status"), "by_institution": inst,
        "recent": [ser(e) for e in db.audit.find().sort("seq", -1).limit(6)] if u["role"] != "institution" else []}

@app.get("/api/users")
def users(u=Depends(auth("admin"))): return [{"id": x["_id"], "name": x["name"], "email": x["email"], "role": x["role"], "institution": x.get("institution")} for x in db.users.find()]
@app.post("/api/users/{uid_}/role")
def set_role(uid_: str, b: dict, u=Depends(auth("admin"))):
    if b.get("role") not in ("institution", "bank", "officer", "senior", "admin"): raise HTTPException(400, "Bad role")
    db.users.update_one({"_id": uid_}, {"$set": {"role": b["role"]}}); audit(u, None, "Role changed", None, {"user": uid_, "role": b["role"]}); return {"ok": True}

# ---------- SCHEDULER (expiry notices) ----------
def expiry_job():
    """Runs daily. One notice per FDR per milestone (dedup via key)."""
    n = 0
    for f in db.fdrs.find({"closed": False}):
        d = days_left(f["maturity_date"]); i, no = f["institution"], f["fdr_no"]
        if d < 0: before = db.notices.count_documents({}); notice(i, no, "FDR expired - action required", "expiry", f"{no} matured {-d} day(s) ago. Submit renewal or release request.", f"{f['_id']}:expired"); notice("AICTE", no, "FDR matured - needs attention", "expiry", f"{no} ({i}) is past maturity.", f"{f['_id']}:expired")
        else:
            ms = [m for m in (7, 15, 30, 60) if d <= m]
            if not ms: continue
            m = ms[0]; t = {60: "Advance expiry reminder", 30: "Renewal reminder", 15: "Urgent expiry notice", 7: "Final expiry reminder"}[m]
            notice(i, no, t, "expiry", f"{no} matures in {d} day(s) on {f['maturity_date']}.", f"{f['_id']}:{m}")
            if m <= 15: notice("AICTE", no, t, "expiry", f"{no} ({i}) matures in {d} day(s).", f"{f['_id']}:{m}")
@app.post("/api/run-scheduler")
def run_sched(u=Depends(auth("officer", "admin", "senior"))): expiry_job(); return {"ok": True}

# ---------- SEED ----------
def seed():
    INST = [("Pune Institute of Engineering", "inst@demo.in"), ("Deccan College of Technology", "inst2@demo.in"), ("Sahyadri Institute of Management", "inst3@demo.in"), ("Konkan Polytechnic", "inst4@demo.in"), ("Vidarbha School of Pharmacy", "inst5@demo.in")]
    U = [(n, e, "institution", n, None) for n, e in INST] + [("SBI Representative", "bank@demo.in", "bank", None, BANKS[0]), ("HDFC Representative", "bank2@demo.in", "bank", None, BANKS[1]),
         ("Officer Meera Kulkarni", "officer@demo.in", "officer", "AICTE", None), ("Senior Officer R. Deshmukh", "senior@demo.in", "senior", "AICTE", None), ("System Admin", "admin@demo.in", "admin", "AICTE", None)]
    for n, e, r, i, b in U: db.users.insert_one({"_id": uid("USR"), "name": n, "email": e, "password": pw("Demo@123"), "role": r, "institution": i, "bank": b})
    sysu = {"name": "System (seed)", "role": "admin"}; OFF = [-80, -20, 3, 6, 14, 25, 29, 45, 58, 100, 200, 365]
    for n in range(22):
        inst = INST[n % 5][0]; bank = BANKS[n % 2]; mat = today() + dt.timedelta(days=OFF[n % 12]); p = n % 6
        e = {"fdr_no": f"{'SBI' if n % 2 == 0 else 'HDF'}{2024000 + n * 37}", "bank": bank, "amount": float((5 + (n * 3) % 20) * 100000), "issue_date": str(mat - dt.timedelta(days=730)), "maturity_date": str(mat)}
        if n == 21: e["fdr_no"] = db.fdrs.find_one({"institution": INST[2][0]})["fdr_no"]  # deliberate duplicate case
        h = None if n == 3 else hashlib.sha256(f"doc{2 if n == 21 else n}".encode()).hexdigest()
        x = dict(e); 
        if p == 5: x["amount"] = e["amount"] * 1.2
        f = build(inst, e, h, None if n == 3 else f"fdr_{n}.pdf", x, "demo"); assign_bank(f)
        if p in (0, 4): f["status"] = "Bank Confirmed"; f["trust"] = {k: "Bank Confirmed" for k in FIELDS}
        if p == 2: f["status"] = "Discrepancy Reported"; f["trust"] = {k: ("Discrepancy" if k == "amount" else "Bank Confirmed") for k in FIELDS}
        if p == 3: f["status"] = "Unverified"; f["trust"] = {k: "Unverified" for k in FIELDS}
        db.fdrs.insert_one(f); audit(sysu, f["_id"], "FDR submitted (sample data)", None, e)
    ok = list(db.fdrs.find({"status": "Bank Confirmed"}))
    iu = db.users.find_one({"role": "institution"})
    make_request(sysu, ok[0], "release", "Matured FDR - requesting release"); make_request(sysu, ok[1], "renewal", "Renewing for 1 year", "REN-778201")
    for f in db.fdrs.find(): 
        if f["mismatches"]: notice(f["institution"], f["fdr_no"], "Document correction required", "action", f["mismatches"][0]["message"])
        if f["duplicates"]: notice(f["institution"], f["fdr_no"], "Potential duplicate detected", "action", "Flagged for officer review (not a fraud finding).")
    expiry_job()

@app.on_event("startup")
def start():
    if db.users.count_documents({}) == 0: seed()
    s = BackgroundScheduler(); s.add_job(expiry_job, "interval", hours=24); s.start()
