import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock, pymongo; pymongo.MongoClient = mongomock.MongoClient
import pytest, main
from fastapi.testclient import TestClient
PDF = b"%PDF-1.4 sample"
F = dict(fdr_no="SBI9999001", bank="State Bank of India", amount=1000000, issue_date="2025-11-15", maturity_date="2027-01-01")
@pytest.fixture(scope="module")
def c():
    with TestClient(main.app) as c: yield c
def L(c, e): return {"Authorization": "Bearer " + c.post("/api/login", json={"email": e, "password": "Demo@123"}).json()["token"]}
def test_flow(c):
    i = L(c, "inst@demo.in"); r = c.post("/api/fdrs", headers=i, data=F, files={"file": ("a_mismatch.pdf", PDF)}); j = r.json()
    assert r.status_code == 200 and j["mismatches"] and "verify_token" not in j          # OCR demo fallback + no token leak
    assert c.post("/api/fdrs", headers=i, data=F, files={"file": ("x.exe", b"MZ")}).status_code == 400   # file validation
    assert c.get(f"/api/fdrs/{j['id']}", headers=L(c, "inst2@demo.in")).status_code == 404            # institution isolation
    assert c.get(f"/api/fdrs/{j['id']}/document", headers=i).status_code == 200                       # encrypted doc round-trip
    tok = c.get(f"/api/fdrs/{j['id']}", headers=L(c, "officer@demo.in")).json()["verify_token"]
    assert c.get("/api/bank-link/" + tok).json()["fdr"]["fdr_no"] == "SBI9999001"
    assert c.post("/api/bank-link/" + tok, json={"confirm": {k: True for k in main.FIELDS}}).json()["status"] == "Bank Confirmed"
    assert c.get("/api/bank-link/" + tok).status_code == 404                                           # single use
    rep = c.post(f"/api/fdrs/{j['id']}/replace", headers=i, data={**F, "fdr_no": "SBI9999002"}, files={"file": ("b.pdf", PDF)}).json()
    assert c.get(f"/api/fdrs/{rep['id']}", headers=i).json()["lineage"][0]["fdr_no"] == "SBI9999001"   # replacement linked
    a = L(c, "admin@demo.in"); assert c.post("/api/admin/simulate-date", headers=a, json={"date": "2030-01-01"}).status_code == 200
    assert any("expired" in n["title"] for n in c.get("/api/notices", headers=i).json())
    c.post("/api/admin/simulate-date", headers=a, json={"date": ""})
    assert c.get("/api/audit", headers=L(c, "officer@demo.in")).json()["chain_valid"]
def test_lockout(c):
    for _ in range(5): c.post("/api/login", json={"email": "inst3@demo.in", "password": "bad"})
    assert c.post("/api/login", json={"email": "inst3@demo.in", "password": "Demo@123"}).status_code == 429
