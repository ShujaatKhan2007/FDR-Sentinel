"""FDR SENTINEL backend (FastAPI + MongoDB). Single file, grouped by section for beginners."""
import os, io, re, json, uuid, hmac, base64, secrets, hashlib, datetime as dt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import jwt
load_dotenv()
db = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))[os.getenv("DB_NAME", "fdr_sentinel")]
PROD = os.getenv("ENV") == "production"
SECRET = os.getenv("JWT_SECRET")
if not SECRET:
    if PROD: raise RuntimeError("JWT_SECRET must be set in production")
    SECRET = "dev-secret"
if PROD and not os.getenv("DOC_KEY"): raise RuntimeError("DOC_KEY (Fernet key) must be set in production")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"  # true => bank responses are labelled SIMULATED
MAX_UPLOAD = 5 * 1024 * 1024
from cryptography.fernet import Fernet
FERNET = Fernet(os.getenv("DOC_KEY") or base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))  # documents are encrypted at rest
app = FastAPI(title="FDR SENTINEL")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["*"], allow_headers=["*"])

FIELDS = ["fdr_no", "bank", "amount", "issue_date", "maturity_date"]
LBL = {"fdr_no": "FDR number", "bank": "Bank name", "amount": "Amount", "issue_date": "Issue date", "maturity_date": "Maturity date"}
BANK_ALIASES = {"State Bank of India": ["state bank of india", "sbi"], "HDFC Bank": ["hdfc"], "Canara Bank": ["canara"], "Punjab National Bank": ["punjab national", "pnb"]}
BANKS = list(BANK_ALIASES)
uid = lambda p: f"{p}-{uuid.uuid4().hex[:6].upper()}"
SIM = None  # simulated 'today' (admin demo control); None = real date
today = lambda: SIM or dt.date.today()
now = lambda: dt.datetime.now().isoformat(timespec="seconds")
def ser(d):
    if d and "_id" in d: d["id"] = d.pop("_id")
    return d
def pw(p, salt=None):
    salt = salt or secrets.token_hex(8)  # per-user random salt
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), salt.encode(), 100000).hex()
def check_pw(p, stored): return hmac.compare_digest(pw(p, stored.split("$")[0]), stored)
def check_upload(data, name):
    if len(data) > MAX_UPLOAD: raise HTTPException(400, "File too large (max 5 MB)")
    if not (data[:4] == b"%PDF" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"): raise HTTPException(400, "Only PDF, PNG or JPG files are accepted")
def store_doc(fid, name, data):
    db.docs.replace_one({"_id": fid}, {"_id": fid, "name": re.sub(r"[^\w.\-]", "_", name or "document"), "data": FERNET.encrypt(data), "size": len(data)}, upsert=True)

@app.middleware("http")
async def security_headers(request, call_next):
    r = await call_next(request); r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}); return r

# ---------- AUTH ----------
def auth(*roles):
    def dep(authorization: str = Header(None)):
        try: p = jwt.decode((authorization or "").replace("Bearer ", ""), SECRET, algorithms=["HS256"])
        except Exception: raise HTTPException(401, "Session expired. Please log in again.")
        u = db.users.find_one({"_id": p["sub"]})
        if not u: raise HTTPException(401, "User not found")
        if not u.get("active", True): raise HTTPException(403, "Account disabled")
        if roles and u["role"] not in roles: raise HTTPException(403, "Not allowed for your role")
        return u
    return dep

@app.post("/api/login")
def login(b: dict):
    u = db.users.find_one({"email": str(b.get("email", "")).lower()})
    if u and u.get("locked_until", "") > now(): raise HTTPException(429, "Too many failed attempts. Try again in 10 minutes.")
    if not u or not check_pw(str(b.get("password", "")), u["password"]):
        if u:
            n = u.get("fails", 0) + 1
            db.users.update_one({"_id": u["_id"]}, {"$set": {"fails": n, "locked_until": (dt.datetime.now() + dt.timedelta(minutes=10)).isoformat(timespec="seconds") if n >= 5 else ""}})
        raise HTTPException(401, "Invalid email or password")
    if not u.get("active", True): raise HTTPException(403, "Account disabled. Contact the administrator.")
    db.users.update_one({"_id": u["_id"]}, {"$set": {"fails": 0, "locked_until": ""}})
    tok = jwt.encode({"sub": u["_id"], "exp": dt.datetime.utcnow() + dt.timedelta(hours=12)}, SECRET, algorithm="HS256")
    return {"token": tok, "user": {k: u[k] for k in ("name", "email", "role", "institution", "bank")}}

@app.post("/api/register")
def register(b: dict):
    """Institution onboarding."""
    if not all(b.get(k) for k in ("name", "email", "password", "institution")): raise HTTPException(400, "All fields are required")
    if len(b["password"]) < 8: raise HTTPException(400, "Password must be at least 8 characters")
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
    q = {"fdr_no": fdr_no}
    if inst != "AICTE": q["institution"] = inst
    rec = db.fdrs.find_one(q)
    db.notices.insert_one({"_id": uid("NTC"), "fdr_id": rec["_id"] if rec else None, "inst": inst, "fdr_no": fdr_no, "title": title, "category": cat, "desc": desc, "time": now(), "read": False, "key": key})

@app.get("/api/notices")
def notices(u=Depends(auth("institution", "officer", "senior"))):
    inst = u["institution"] if u["role"] == "institution" else "AICTE"
    return [ser(n) for n in db.notices.find({"inst": inst}).sort("time", -1)]
@app.post("/api/notices/{nid}/read")
def read_notice(nid: str, u=Depends(auth())):
    db.notices.update_one({"_id": nid}, {"$set": {"read": True}}); return {"ok": True}

# ---------- OCR, COMPARISON, DUPLICATES, RISK ----------
DATE_RX = r"\d{4}-\d{2}-\d{2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
def to_iso(s):
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try: return dt.datetime.strptime(re.sub(r"\s+", " ", s.strip()), f).date().isoformat()
        except ValueError: pass

def parse_text(t):
    """Pull the five key fields out of raw OCR / PDF text."""
    x = {}
    m = re.search(r"(?:FDR|Receipt|Deposit)\s*(?:No\.?|Number|#)?\s*[:\-]?\s*([A-Z]{0,5}\d[A-Z0-9\-/]{4,})", t, re.I); x["fdr_no"] = m.group(1).upper() if m else None
    m = re.search(r"(?:Rs\.?|₹|INR)\s*([\d,]+(?:\.\d+)?)", t); x["amount"] = float(m.group(1).replace(",", "")) if m else None
    low = t.lower(); x["bank"] = next((b for b, al in BANK_ALIASES.items() if any(a in low for a in al)), None)
    iss = mat = None; found = []
    for m in re.finditer(DATE_RX, t):
        d = to_iso(m.group())
        if not d: continue
        ctx = low[max(0, m.start() - 40):m.start()]
        if "matur" in ctx or "due" in ctx: mat = mat or d
        elif "issue" in ctx or "deposit" in ctx or "start" in ctx: iss = iss or d
        found.append(d)
    if not (iss and mat) and len(found) >= 2: iss, mat = iss or min(found), mat or max(found)
    x["issue_date"], x["maturity_date"] = iss, mat
    return x

def run_ocr(data, filename, e):
    """Real extraction: PDF text layer (pypdf) -> Tesseract -> RapidOCR. If nothing can read the file, fall back to
    clearly labelled DEMO data (never presented as a real result). OCR does not prove a document is genuine."""
    text, src = "", "none"
    try:
        if data[:4] == b"%PDF":
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages); src = "pdf-text-layer"
        else:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            try: import pytesseract; text = pytesseract.image_to_string(img); src = "tesseract"
            except Exception:
                from rapidocr_onnxruntime import RapidOCR; import numpy as np
                res, _ = RapidOCR()(np.array(img.convert("RGB"))); text = "\n".join(r[1] for r in (res or [])); src = "rapidocr"
    except Exception: text = ""
    if text.strip(): return parse_text(text), src
    x = dict(e)  # DEMO fallback. Put 'mismatch' in the file name to simulate a wrong amount.
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
    f["verify_token"] = secrets.token_urlsafe(24)  # single-use secure verification link

# ---------- FDR ENDPOINTS ----------
@app.get("/api/fdrs")
def list_fdrs(u=Depends(auth())):
    q = {"institution": u["institution"]} if u["role"] == "institution" else {"bank_user": u["_id"]} if u["role"] == "bank" else {}
    return [enrich({k: v for k, v in f.items() if k != "verify_token"}) for f in db.fdrs.find(q)]

@app.get("/api/fdrs/{fid}")
def one_fdr(fid: str, u=Depends(auth())):
    f = db.fdrs.find_one({"_id": fid})
    if not f or (u["role"] == "institution" and f["institution"] != u["institution"]) or (u["role"] == "bank" and f.get("bank_user") != u["_id"]): raise HTTPException(404, "Record not found")
    f = enrich(f); f["checklist"] = checklist(f); f["lineage"] = lineage(f); f["has_doc"] = bool(db.docs.find_one({"_id": fid}, {"_id": 1}))
    if u["role"] not in ("officer", "senior", "admin"): f.pop("verify_token", None)
    return f

def parse_fields(fdr_no, bank, amount, issue_date, maturity_date):
    try: i, m = dt.date.fromisoformat(issue_date), dt.date.fromisoformat(maturity_date)
    except ValueError: raise HTTPException(400, "Dates must be YYYY-MM-DD")
    if amount <= 0 or m <= i: raise HTTPException(400, "Amount must be positive and maturity must be after issue date")
    if bank not in BANKS: raise HTTPException(400, "Unsupported bank")
    if not re.fullmatch(r"[A-Za-z0-9\-/]{5,30}", fdr_no.strip()): raise HTTPException(400, "FDR number must be 5-30 letters, digits, - or /")
    return {"fdr_no": fdr_no.strip().upper(), "bank": bank, "amount": amount, "issue_date": issue_date, "maturity_date": maturity_date}

async def create_fdr(u, e, file, replaces=None):
    """Shared by new submissions and replacement FDRs: validate file, OCR, compare, duplicate check, store encrypted, audit, notify."""
    data = await file.read() if file else b""
    if data: check_upload(data, file.filename)
    h = hashlib.sha256(data).hexdigest() if data else None
    x, src = run_ocr(data, file.filename, e) if data else ({}, "none")
    f = build(u["institution"], e, h, file.filename if file else None, x, src); assign_bank(f)
    if replaces: f["replaces"] = replaces
    db.fdrs.insert_one(f)
    if data: store_doc(f["_id"], file.filename, data)
    audit(u, f["_id"], "Replacement FDR submitted" if replaces else "FDR submitted", None, e)
    if f["mismatches"]: notice(u["institution"], e["fdr_no"], "Document correction required", "action", "; ".join(m["message"] for m in f["mismatches"]))
    if f["duplicates"]:
        notice(u["institution"], e["fdr_no"], "Potential duplicate FDR alert", "action", "This record resembles an existing one and is flagged for officer review (not a fraud finding).")
        notice("AICTE", e["fdr_no"], "Potential duplicate flagged", "action", f"{u['institution']} submitted {e['fdr_no']}; matches existing record(s).")
    if risk(f, days_left(e["maturity_date"]))["priority"] == "High": notice("AICTE", e["fdr_no"], "High-priority alert", "action", f"{e['fdr_no']} from {u['institution']} needs scrutiny.")
    return f

@app.post("/api/fdrs")
async def add_fdr(fdr_no: str = Form(...), bank: str = Form(...), amount: float = Form(...), issue_date: str = Form(...), maturity_date: str = Form(...), file: UploadFile = File(None), u=Depends(auth("institution"))):
    f = await create_fdr(u, parse_fields(fdr_no, bank, amount, issue_date, maturity_date), file); f.pop("verify_token", None); return enrich(f)

@app.post("/api/fdrs/{fid}/replace")
async def replace_fdr(fid: str, fdr_no: str = Form(...), bank: str = Form(...), amount: float = Form(...), issue_date: str = Form(...), maturity_date: str = Form(...), remarks: str = Form(""), file: UploadFile = File(None), u=Depends(auth("institution"))):
    """Renewal / replacement: new FDR record linked to the original (original is preserved, never overwritten)."""
    old = db.fdrs.find_one({"_id": fid, "institution": u["institution"]})
    if not old or old.get("closed"): raise HTTPException(404, "Record not found")
    f = await create_fdr(u, parse_fields(fdr_no, bank, amount, issue_date, maturity_date), file, replaces=fid)
    db.fdrs.update_one({"_id": fid}, {"$push": {"replaced_by": f["_id"]}})
    r = make_request(u, old, "renewal", remarks or "Replacement FDR submitted", f["fdr_no"]); db.requests.update_one({"_id": r["_id"]}, {"$set": {"replacement_fdr_id": f["_id"]}})
    audit(u, fid, "Replacement FDR linked", None, {"replacement": f["_id"], "fdr_no": f["fdr_no"]}); f.pop("verify_token", None); return enrich(f)

def lineage(f):
    """Original <-> replacement chain, so renewal history is preserved."""
    out, cur, n = [], f, 0
    while cur.get("replaces") and n < 10:
        cur = db.fdrs.find_one({"_id": cur["replaces"]}); n += 1
        if not cur: break
        out.insert(0, {"id": cur["_id"], "fdr_no": cur["fdr_no"], "status": cur["status"], "maturity_date": cur["maturity_date"], "rel": "Original / earlier"})
    for rid in f.get("replaced_by", []):
        c = db.fdrs.find_one({"_id": rid})
        if c: out.append({"id": c["_id"], "fdr_no": c["fdr_no"], "status": c["status"], "maturity_date": c["maturity_date"], "rel": "Replacement"})
    return out

def doc_response(fid):
    d = db.docs.find_one({"_id": fid})
    if not d: raise HTTPException(404, "No stored document for this record (demo record)")
    data = FERNET.decrypt(bytes(d["data"]))
    mt = "application/pdf" if data[:4] == b"%PDF" else "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(data, media_type=mt, headers={"Content-Disposition": f'inline; filename="{d["name"]}"'})

@app.get("/api/fdrs/{fid}/document")
def get_doc(fid: str, u=Depends(auth())):
    one_fdr(fid, u)  # same access rules as the record itself
    return doc_response(fid)

def apply_bank(f, actor, conf, remarks, via):
    """Record a bank response. Labelled SIMULATED while DEMO_MODE=true. No response => record stays Unverified/Pending."""
    trust = {k: ("Bank Confirmed" if conf.get(k) else "Discrepancy") for k in FIELDS}
    status = "Bank Confirmed" if all(conf.get(k) for k in FIELDS) else "Discrepancy Reported"
    audit(actor, f["_id"], "Bank verification" + (" (simulated)" if DEMO_MODE else ""), {"status": f["status"], "trust": f["trust"]}, {"status": status, "trust": trust})
    db.fdrs.update_one({"_id": f["_id"]}, {"$set": {"trust": trust, "status": status, "bank_remarks": remarks, "verified_by": actor["name"], "verified_at": now(), "simulated": DEMO_MODE, "verified_via": via, "verify_token": None}})
    if status == "Bank Confirmed": notice(f["institution"], f["fdr_no"], "Bank verification completed", "verification", "All fields confirmed by the bank." + (" (prototype/demo verification)" if DEMO_MODE else ""))
    else: notice(f["institution"], f["fdr_no"], "Bank discrepancy reported", "action", f"Remarks: {remarks or 'see record'}. Please review and correct the record.")
    return status

@app.post("/api/fdrs/{fid}/bank")
def bank_verify(fid: str, b: dict, u=Depends(auth("bank"))):
    f = db.fdrs.find_one({"_id": fid, "bank_user": u["_id"]})
    if not f: raise HTTPException(404, "Not assigned to you")
    if f["status"] != "Pending Bank Verification": raise HTTPException(400, "This request has already been answered")
    return {"status": apply_bank(f, u, b.get("confirm", {}), str(b.get("remarks", ""))[:500], "bank login")}

def link_fdr(token):
    f = db.fdrs.find_one({"verify_token": token}) if token and len(token) > 16 else None
    if not f: raise HTTPException(404, "This verification link is invalid or has already been used")
    return f
@app.get("/api/bank-link/{token}")  # restricted page: no login, one request only
def bank_link_get(token: str):
    f = link_fdr(token); return {"bank": f["bank"], "institution": f["institution"], "fdr": {k: f[k] for k in FIELDS}, "has_doc": bool(db.docs.find_one({"_id": f["_id"]}, {"_id": 1})), "simulated": DEMO_MODE}
@app.get("/api/bank-link/{token}/document")
def bank_link_doc(token: str): return doc_response(link_fdr(token)["_id"])
@app.post("/api/bank-link/{token}")
def bank_link_post(token: str, b: dict):
    f = link_fdr(token); actor = {"name": f"{f['bank']} representative (secure link)", "role": "bank"}
    return {"status": apply_bank(f, actor, b.get("confirm", {}), str(b.get("remarks", ""))[:500], "secure link")}

@app.post("/api/fdrs/{fid}/review")
def review(fid: str, b: dict, u=Depends(auth("officer", "senior"))):
    """Officer scrutiny actions: reviewed / note / request correction / escalate / (senior) resolve."""
    f = db.fdrs.find_one({"_id": fid}); a = b.get("action"); note = str(b.get("note") or "").strip()[:500]
    if not f or a not in ("mark_reviewed", "request_correction", "escalate", "resolve_escalation", "add_note"): raise HTTPException(400, "Invalid action")
    if a == "resolve_escalation" and u["role"] != "senior": raise HTTPException(403, "Only a senior officer can resolve escalations")
    if a != "mark_reviewed" and not note: raise HTTPException(400, "A note is required for this action")
    op = {"$push": {"reviews": {"by": u["name"], "role": u["role"], "action": a, "note": note, "time": now()}}}
    if a in ("escalate", "resolve_escalation"): op["$set"] = {"escalated": a == "escalate"}
    db.fdrs.update_one({"_id": fid}, op); audit(u, fid, f"Officer action: {a.replace('_', ' ')}", None, {"note": note})
    if a == "request_correction": notice(f["institution"], f["fdr_no"], "Correction required", "action", note)
    if a == "escalate": notice("AICTE", f["fdr_no"], "Case escalated to senior officer", "action", f"{f['fdr_no']} ({f['institution']}): {note}")
    return {"ok": True}

# ---------- RENEWAL / RELEASE ----------
CHECKS = {"bank_confirmed": "Bank confirmation for all fields", "no_discrepancy": "No unresolved discrepancy", "no_duplicate": "No potential-duplicate flag", "matured": "FDR has reached maturity", "docs_present": "Supporting document on file"}
def cfg():
    c = db.settings.find_one({"_id": "config"}) or {}
    return {"milestones": c.get("milestones", [60, 30, 15, 7]), "checks": c.get("checks", list(CHECKS))}
def checklist(f):  # ILLUSTRATIVE and admin-configurable: validate against official AICTE rules before real use
    ok = {"bank_confirmed": f["status"] == "Bank Confirmed", "no_discrepancy": f["status"] != "Discrepancy Reported", "no_duplicate": not f.get("duplicates"), "matured": days_left(f["maturity_date"]) <= 0, "docs_present": bool(f.get("file_hash"))}
    return [{"item": CHECKS[k], "ok": ok[k]} for k in cfg()["checks"] if k in CHECKS]

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
    if d == "approve": db.fdrs.update_one({"_id": r["fdr_id"]}, {"$set": {"closed": True, "closure_reason": "Renewed / replaced" if r["type"] == "renewal" else "Released"}})
    audit(u, r["fdr_id"], f"{r['type'].title()} request {st.lower()}", {"status": r["status"]}, {"status": st})
    notice(r["institution"], r["fdr_no"], f"{r['type'].title()} status updated", "action" if d != "approve" else "verification", f"Your {r['type']} request is now: {st}.")
    return {"status": st}

# ---------- DASHBOARD / ADMIN ----------
def monthly(fs):
    """Submissions per month for the last 6 months, from real records."""
    out = {}; t = today().replace(day=1)
    for i in range(5, -1, -1):
        y, m = t.year, t.month - i
        while m < 1: m += 12; y -= 1
        out[f"{y}-{m:02d}"] = 0
    for f in fs:
        k = f["created"][:7]
        if k in out: out[k] += 1
    return out

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
        "by_status": by("status"), "risk_dist": {k: c(lambda f: f["risk"]["priority"] == k) for k in ("High", "Medium", "Low")}, "monthly": monthly(fs), "by_expiry": by("expiry_status"), "by_institution": inst,
        "recent": [ser(e) for e in db.audit.find().sort("seq", -1).limit(6)] if u["role"] != "institution" else []}

@app.get("/api/users")
def users(u=Depends(auth("admin"))): return [{"id": x["_id"], "name": x["name"], "email": x["email"], "role": x["role"], "institution": x.get("institution"), "bank": x.get("bank"), "active": x.get("active", True)} for x in db.users.find()]
@app.post("/api/users/{uid_}/role")
def set_role(uid_: str, b: dict, u=Depends(auth("admin"))):
    if b.get("role") not in ("institution", "bank", "officer", "senior", "admin"): raise HTTPException(400, "Bad role")
    db.users.update_one({"_id": uid_}, {"$set": {"role": b["role"]}}); audit(u, None, "Role changed", None, {"user": uid_, "role": b["role"]}); return {"ok": True}

@app.post("/api/fdrs/{fid}/correct")
async def correct(fid: str, fdr_no: str = Form(...), bank: str = Form(...), amount: float = Form(...), issue_date: str = Form(...), maturity_date: str = Form(...), file: UploadFile = File(None), u=Depends(auth("institution"))):
    """Institution responds to a correction notice: edit details and/or re-upload; checks re-run; record returns to the bank."""
    f = db.fdrs.find_one({"_id": fid, "institution": u["institution"]})
    if not f or f.get("closed"): raise HTTPException(404, "Record not found")
    try: i, m = dt.date.fromisoformat(issue_date), dt.date.fromisoformat(maturity_date)
    except ValueError: raise HTTPException(400, "Dates must be YYYY-MM-DD")
    if amount <= 0 or m <= i: raise HTTPException(400, "Amount must be positive and maturity must be after issue date")
    e = {"fdr_no": fdr_no.strip(), "bank": bank, "amount": amount, "issue_date": issue_date, "maturity_date": maturity_date}
    h, fname, x, src = f.get("file_hash"), f.get("file_name"), f.get("extracted", {}), f.get("ocr_source", "none")
    data = await file.read() if file else b""
    if data: check_upload(data, file.filename); store_doc(fid, file.filename, data); h, fname = hashlib.sha256(data).hexdigest(), file.filename; x, src = run_ocr(data, fname, e)
    upd = {**e, "file_hash": h, "file_name": fname, "extracted": x, "ocr_source": src, "mismatches": compare(e, x) if src != "none" else [], "duplicates": find_dups(e, h, fid), "status": "Pending Bank Verification", "trust": {k: "Institution Submitted" for k in FIELDS}, "verify_token": secrets.token_urlsafe(24)}
    audit(u, fid, "Correction submitted", {k: f[k] for k in FIELDS}, e); db.fdrs.update_one({"_id": fid}, {"$set": upd})
    notice(u["institution"], e["fdr_no"], "Correction received", "verification", "Checks were re-run and the record was sent for bank verification.")
    return {"ok": True}

# ---------- SCHEDULER (expiry notices) ----------
MS_TITLE = {60: "Advance expiry reminder", 30: "Renewal reminder", 15: "Urgent expiry notice", 7: "Final expiry reminder"}
def expiry_job():
    """Scheduled daily (and on demand). One notice per FDR per milestone (dedup key). Thresholds come from admin config."""
    ms_all = sorted(cfg()["milestones"])
    for f in db.fdrs.find({"closed": {"$ne": True}}):
        d = days_left(f["maturity_date"]); i, no = f["institution"], f["fdr_no"]
        if d < 0:
            notice(i, no, "FDR expired - action required", "expiry", f"FDR {no} matured {-d} day(s) ago. Action required: submit a renewal/replacement or a release request through the portal.", f"{f['_id']}:expired")
            notice("AICTE", no, "FDR matured - needs attention", "expiry", f"{no} ({i}) is past maturity.", f"{f['_id']}:expired")
        else:
            ms = [m for m in ms_all if d <= m]
            if not ms: continue
            m = ms[0]; t = MS_TITLE.get(m, f"Expiry reminder ({m} days)")
            notice(i, no, t, "expiry", f"{'Urgent: ' if m <= 15 else ''}FDR {no} matures in {d} day(s) on {f['maturity_date']}. Please initiate the renewal or replacement process and update the FDR record through the portal.", f"{f['_id']}:{m}")
            if m <= 15: notice("AICTE", no, t, "expiry", f"{no} ({i}) matures in {d} day(s).", f"{f['_id']}:{m}")

@app.post("/api/run-scheduler")
def run_sched(u=Depends(auth("officer", "admin", "senior"))): expiry_job(); return {"ok": True}

ROLES = ("institution", "bank", "officer", "senior", "admin")
@app.get("/api/health")
def health(): db.command("ping"); return {"ok": True}

@app.post("/api/users")
def add_user(b: dict, u=Depends(auth("admin"))):
    if b.get("role") not in ROLES or not all(b.get(k) for k in ("name", "email", "password")) or len(b["password"]) < 8: raise HTTPException(400, "Name, email, role and an 8+ character password are required")
    if b["role"] == "institution" and not b.get("institution"): raise HTTPException(400, "Institution name required")
    if b["role"] == "bank" and b.get("bank") not in BANKS: raise HTTPException(400, "Choose a bank")
    if db.users.find_one({"email": b["email"].lower()}): raise HTTPException(400, "Email already exists")
    db.users.insert_one({"_id": uid("USR"), "name": b["name"], "email": b["email"].lower(), "password": pw(b["password"]), "role": b["role"], "institution": b.get("institution") or ("AICTE" if b["role"] != "bank" else None), "bank": b.get("bank"), "active": True})
    audit(u, None, "User created", None, {"email": b["email"], "role": b["role"]}); return {"ok": True}
@app.post("/api/users/{uid_}/active")
def set_active(uid_: str, b: dict, u=Depends(auth("admin"))):
    if uid_ == u["_id"]: raise HTTPException(400, "You cannot disable your own account")
    db.users.update_one({"_id": uid_}, {"$set": {"active": bool(b.get("active"))}}); audit(u, None, "User enabled/disabled", None, {"user": uid_, "active": bool(b.get("active"))}); return {"ok": True}
@app.post("/api/users/{uid_}/password")
def reset_pw(uid_: str, b: dict, u=Depends(auth("admin"))):
    if len(str(b.get("password", ""))) < 8: raise HTTPException(400, "Password must be at least 8 characters")
    db.users.update_one({"_id": uid_}, {"$set": {"password": pw(b["password"]), "fails": 0, "locked_until": ""}}); audit(u, None, "Password reset by admin", None, {"user": uid_}); return {"ok": True}
@app.post("/api/me/password")
def my_pw(b: dict, u=Depends(auth())):
    if not check_pw(str(b.get("old", "")), u["password"]): raise HTTPException(400, "Current password is incorrect")
    if len(str(b.get("new", ""))) < 8: raise HTTPException(400, "New password must be at least 8 characters")
    db.users.update_one({"_id": u["_id"]}, {"$set": {"password": pw(b["new"])}}); audit(u, None, "Password changed", None, None); return {"ok": True}

@app.post("/api/admin/simulate-date")
def sim_date(b: dict, u=Depends(auth("admin"))):
    """Controlled date simulation for demos (15-day, 7-day, overdue notices). Empty date = real date."""
    global SIM
    try: SIM = dt.date.fromisoformat(b["date"]) if b.get("date") else None
    except ValueError: raise HTTPException(400, "Use YYYY-MM-DD")
    db.settings.update_one({"_id": "sim"}, {"$set": {"date": b.get("date") or None}}, upsert=True)
    expiry_job(); audit(u, None, "System date simulated", None, {"date": b.get("date") or "real date"}); return {"date": str(today())}
@app.get("/api/admin/system")
def system(u=Depends(auth("admin"))):
    return {"today": str(today()), "simulated": SIM is not None, "demo_mode": DEMO_MODE, "config": cfg(), "all_checks": CHECKS, "counts": {c: db[c].count_documents({}) for c in ("users", "fdrs", "notices", "audit", "requests")}}
@app.post("/api/admin/config")
def set_cfg(b: dict, u=Depends(auth("admin"))):
    try: ms = sorted({int(x) for x in b.get("milestones", [])}, reverse=True)
    except (TypeError, ValueError): raise HTTPException(400, "Reminder days must be numbers")
    if not ms or min(ms) < 1: raise HTTPException(400, "Provide at least one positive reminder day")
    db.settings.update_one({"_id": "config"}, {"$set": {"milestones": ms, "checks": [k for k in b.get("checks", []) if k in CHECKS]}}, upsert=True)
    audit(u, None, "System configuration changed", None, {"milestones": ms}); return cfg()

# ---------- SEED ----------
def seed():
    INST = [("Pune Institute of Engineering", "inst@demo.in"), ("Deccan College of Technology", "inst2@demo.in"), ("Sahyadri Institute of Management", "inst3@demo.in"), ("Konkan Polytechnic", "inst4@demo.in"), ("Vidarbha School of Pharmacy", "inst5@demo.in")]
    U = [(n, e, "institution", n, None) for n, e in INST] + [("SBI Representative", "bank@demo.in", "bank", None, BANKS[0]), ("HDFC Representative", "bank2@demo.in", "bank", None, BANKS[1]), ("Canara Representative", "bank3@demo.in", "bank", None, BANKS[2]), ("PNB Representative", "bank4@demo.in", "bank", None, BANKS[3]),
         ("Officer Meera Kulkarni", "officer@demo.in", "officer", "AICTE", None), ("Senior Officer R. Deshmukh", "senior@demo.in", "senior", "AICTE", None), ("System Admin", "admin@demo.in", "admin", "AICTE", None)]
    for n, e, r, i, b in U: db.users.insert_one({"_id": uid("USR"), "name": n, "email": e, "password": pw("Demo@123"), "role": r, "institution": i, "bank": b})
    sysu = {"name": "System (seed)", "role": "admin"}; OFF = [-80, -20, 3, 6, 14, 25, 29, 45, 58, 100, 200, 365]
    for n in range(22):
        inst = INST[n % 5][0]; bank = BANKS[n % 4]; mat = today() + dt.timedelta(days=OFF[n % 12]); p = n % 6
        e = {"fdr_no": f"{['SBI', 'HDF', 'CNB', 'PNB'][n % 4]}{2024000 + n * 37}", "bank": bank, "amount": float((5 + (n * 3) % 20) * 100000), "issue_date": str(mat - dt.timedelta(days=730)), "maturity_date": str(mat)}
        if n == 21: e["fdr_no"] = db.fdrs.find_one({"institution": INST[2][0]})["fdr_no"]  # deliberate duplicate case
        h = None if n == 3 else hashlib.sha256(f"doc{2 if n == 21 else n}".encode()).hexdigest()
        x = dict(e); 
        if p == 5: x["amount"] = e["amount"] * 1.2
        f = build(inst, e, h, None if n == 3 else f"fdr_{n}.pdf", x, "demo"); assign_bank(f)
        if p in (0, 4): f["status"] = "Bank Confirmed"; f["trust"] = {k: "Bank Confirmed" for k in FIELDS}
        if p == 2: f["status"] = "Discrepancy Reported"; f["trust"] = {k: ("Discrepancy" if k == "amount" else "Bank Confirmed") for k in FIELDS}
        if p == 3: f["status"] = "Unverified"; f["trust"] = {k: "Unverified" for k in FIELDS}
        f["created"] = (dt.datetime.now() - dt.timedelta(days=30 * (n % 6))).isoformat(timespec="seconds")
        db.fdrs.insert_one(f); audit(sysu, f["_id"], "FDR submitted (sample data)", None, e)
    ok = list(db.fdrs.find({"status": "Bank Confirmed"}))
    iu = db.users.find_one({"role": "institution"})
    make_request(sysu, ok[0], "release", "Matured FDR - requesting release"); make_request(sysu, ok[1], "renewal", "Renewing for 1 year", "REN-778201")
    for f in db.fdrs.find(): 
        if f["mismatches"]: notice(f["institution"], f["fdr_no"], "Document correction required", "action", f["mismatches"][0]["message"])
        if f["duplicates"]: notice(f["institution"], f["fdr_no"], "Potential duplicate detected", "action", "Flagged for officer review (not a fraud finding).")
    hi = next((f for f in db.fdrs.find() if risk(f, days_left(f["maturity_date"]))["priority"] == "High"), None)
    if hi: db.fdrs.update_one({"_id": hi["_id"]}, {"$set": {"escalated": True}, "$push": {"reviews": {"by": "Officer Meera Kulkarni", "role": "officer", "action": "escalate", "note": "Mismatch plus pending verification - needs senior review.", "time": now()}}})
    expiry_job()

@app.on_event("startup")
def start():
    global SIM
    db.users.create_index("email", unique=True); db.fdrs.create_index("institution"); db.fdrs.create_index("fdr_no"); db.fdrs.create_index("verify_token"); db.notices.create_index([("inst", 1), ("key", 1)]); db.audit.create_index("seq", unique=True)
    sm = db.settings.find_one({"_id": "sim"}) or {}; SIM = dt.date.fromisoformat(sm["date"]) if sm.get("date") else None
    if db.users.count_documents({}) == 0:
        if os.getenv("SEED_DEMO", "true").lower() == "true": seed()
        elif os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD"): db.users.insert_one({"_id": uid("USR"), "name": "Administrator", "email": os.getenv("ADMIN_EMAIL").lower(), "password": pw(os.getenv("ADMIN_PASSWORD")), "role": "admin", "institution": "AICTE", "active": True})
    sc = BackgroundScheduler(); sc.add_job(expiry_job, "interval", hours=24); sc.start()

# ---------- SINGLE-SERVICE HOSTING: serve the built React app from the same server ----------
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(STATIC):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")  # registered last so /api routes win
