"""
NOC License Server — ARBA Training
Server terpusat untuk validasi dan monitoring lisensi NOC Sentinel v4.

Endpoints:
  POST /validate          — validasi license key dari client
  POST /heartbeat         — update last_seen instance
  GET  /admin/instances   — dashboard semua instance (admin only)
  POST /admin/issue       — buat license key baru (admin only)
  POST /admin/revoke      — cabut/nonaktifkan license (admin only)
  GET  /admin/licenses    — list semua license (admin only)
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from database import connect_db, close_db, get_db
from models import (
    generate_license_key,
    compute_expiry,
    is_license_expired,
    format_license_response,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-me-in-production")
CORS_ORIGINS  = os.getenv("CORS_ORIGINS", "*").split(",")

app = FastAPI(
    title="NOC License Server",
    description="Server lisensi terpusat untuk NOC Sentinel v4 — ARBA Training",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Startup / Shutdown ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await connect_db()
    logger.info("NOC License Server siap.")


@app.on_event("shutdown")
async def shutdown():
    await close_db()


# ── Helper: admin auth ─────────────────────────────────────────────────────────
def require_admin(x_admin_secret: Optional[str] = Header(None)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin secret salah atau tidak ada")


# ── Pydantic Models ────────────────────────────────────────────────────────────
class ValidateRequest(BaseModel):
    license_key: str
    hostname:    str = ""
    ip_address:  str = ""
    version:     str = ""
    device_count: int = 0


class HeartbeatRequest(BaseModel):
    license_key:  str
    hostname:     str = ""
    ip_address:   str = ""
    version:      str = ""
    device_count: int = 0


class IssueRequest(BaseModel):
    customer:     str
    license_type: str   # monthly | yearly | lifetime
    notes:        str = ""


class RevokeRequest(BaseModel):
    license_key: str
    reason:      str = ""


# ── POST /validate ─────────────────────────────────────────────────────────────
@app.post("/validate")
async def validate_license(req: ValidateRequest, request: Request):
    """
    Validasi license key dari NOC Sentinel client.
    Return: {valid, expired, customer, type, expires_at, message}
    """
    db = get_db()
    doc = await db.licenses.find_one({"key": req.license_key})

    if not doc:
        logger.warning(f"VALIDATE FAILED — key not found: {req.license_key} from {req.hostname}/{req.ip_address}")
        raise HTTPException(status_code=404, detail="License key tidak ditemukan")

    expired = is_license_expired(doc)
    valid   = doc.get("is_active", False) and not expired

    # Update instance info dalam license document
    now = datetime.now(timezone.utc)
    await db.licenses.update_one(
        {"key": req.license_key},
        {
            "$set": {f"instances.{_safe_hostname(req.hostname)}.last_seen":    now.isoformat()},
            "$setOnInsert": {},
        }
    )
    # Upsert instance ke array instances (cari berdasarkan hostname)
    existing_instances = doc.get("instances", [])
    updated = False
    for inst in existing_instances:
        if inst.get("hostname") == req.hostname:
            inst.update({
                "ip_address":  req.ip_address,
                "version":     req.version,
                "device_count": req.device_count,
                "last_seen":   now.isoformat(),
                "is_online":   True,
            })
            updated = True
            break
    if not updated:
        existing_instances.append({
            "hostname":     req.hostname,
            "ip_address":   req.ip_address,
            "version":      req.version,
            "device_count": req.device_count,
            "last_seen":    now.isoformat(),
            "is_online":    True,
            "registered_at": now.isoformat(),
        })
    await db.licenses.update_one(
        {"key": req.license_key},
        {"$set": {"instances": existing_instances}}
    )

    expires_at = doc.get("expires_at")
    logger.info(f"VALIDATE {'OK' if valid else 'DENIED'} — {req.license_key} | {req.hostname} | {doc.get('customer')}")

    return {
        "valid":      valid,
        "expired":    expired,
        "active":     doc.get("is_active", False),
        "customer":   doc.get("customer", ""),
        "type":       doc.get("type", ""),
        "expires_at": expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at,
        "message":    "OK" if valid else ("License expired" if expired else "License tidak aktif"),
    }


# ── POST /heartbeat ────────────────────────────────────────────────────────────
@app.post("/heartbeat")
async def heartbeat(req: HeartbeatRequest):
    """Update last_seen instance — dipanggil setiap 5 menit oleh client."""
    db = get_db()
    doc = await db.licenses.find_one({"key": req.license_key})
    if not doc:
        raise HTTPException(status_code=404, detail="License key tidak ditemukan")

    now = datetime.now(timezone.utc)
    instances = doc.get("instances", [])
    updated = False
    for inst in instances:
        if inst.get("hostname") == req.hostname:
            inst["last_seen"]    = now.isoformat()
            inst["ip_address"]   = req.ip_address or inst.get("ip_address", "")
            inst["version"]      = req.version or inst.get("version", "")
            inst["device_count"] = req.device_count
            inst["is_online"]    = True
            updated = True
            break
    if not updated:
        instances.append({
            "hostname":      req.hostname,
            "ip_address":    req.ip_address,
            "version":       req.version,
            "device_count":  req.device_count,
            "last_seen":     now.isoformat(),
            "is_online":     True,
            "registered_at": now.isoformat(),
        })
    await db.licenses.update_one(
        {"key": req.license_key},
        {"$set": {"instances": instances}}
    )
    return {"ok": True, "timestamp": now.isoformat()}


# ── GET /admin/licenses ────────────────────────────────────────────────────────
@app.get("/admin/licenses")
async def admin_list_licenses(x_admin_secret: Optional[str] = Header(None)):
    """List semua license key yang pernah dibuat."""
    require_admin(x_admin_secret)
    db = get_db()
    docs = await db.licenses.find({}).sort("issued_at", -1).to_list(500)
    return {"licenses": [format_license_response(d) for d in docs]}


# ── GET /admin/instances ───────────────────────────────────────────────────────
@app.get("/admin/instances")
async def admin_instances(x_admin_secret: Optional[str] = Header(None)):
    """Dashboard — semua instance dari semua license, lengkap dengan status online/offline."""
    require_admin(x_admin_secret)
    db = get_db()
    docs = await db.licenses.find({}).to_list(500)

    all_instances = []
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

    total_online  = 0
    total_offline = 0

    for doc in docs:
        for inst in doc.get("instances", []):
            ls = inst.get("last_seen")
            if isinstance(ls, str):
                from datetime import datetime as _dt
                try:
                    ls = _dt.fromisoformat(ls)
                except Exception:
                    ls = None
            if ls and ls.tzinfo is None:
                ls = ls.replace(tzinfo=timezone.utc)
            is_online = bool(ls and ls > cutoff)
            if is_online:
                total_online += 1
            else:
                total_offline += 1
            all_instances.append({
                "license_key":   doc["key"],
                "customer":      doc.get("customer", ""),
                "license_type":  doc.get("type", ""),
                "license_active": doc.get("is_active", False),
                "hostname":      inst.get("hostname", ""),
                "ip_address":    inst.get("ip_address", ""),
                "version":       inst.get("version", ""),
                "device_count":  inst.get("device_count", 0),
                "last_seen":     inst.get("last_seen", ""),
                "registered_at": inst.get("registered_at", ""),
                "is_online":     is_online,
            })

    all_instances.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
    return {
        "total_online":  total_online,
        "total_offline": total_offline,
        "instances":     all_instances,
    }


# ── POST /admin/issue ──────────────────────────────────────────────────────────
@app.post("/admin/issue")
async def admin_issue_license(req: IssueRequest, x_admin_secret: Optional[str] = Header(None)):
    """Buat license key baru untuk pelanggan."""
    require_admin(x_admin_secret)
    if req.license_type not in ("monthly", "yearly", "lifetime"):
        raise HTTPException(status_code=400, detail="license_type harus: monthly, yearly, atau lifetime")

    db = get_db()
    key        = generate_license_key()
    now        = datetime.now(timezone.utc)
    expires_at = compute_expiry(req.license_type)

    doc = {
        "key":        key,
        "customer":   req.customer,
        "type":       req.license_type,
        "notes":      req.notes,
        "is_active":  True,
        "issued_at":  now,
        "expires_at": expires_at,
        "instances":  [],
    }
    await db.licenses.insert_one(doc)
    logger.info(f"ISSUED license {key} → {req.customer} ({req.license_type})")

    return {
        "ok":         True,
        "key":        key,
        "customer":   req.customer,
        "type":       req.license_type,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "issued_at":  now.isoformat(),
    }


# ── POST /admin/revoke ─────────────────────────────────────────────────────────
@app.post("/admin/revoke")
async def admin_revoke_license(req: RevokeRequest, x_admin_secret: Optional[str] = Header(None)):
    """Cabut/nonaktifkan license key."""
    require_admin(x_admin_secret)
    db = get_db()
    result = await db.licenses.update_one(
        {"key": req.license_key},
        {"$set": {"is_active": False, "revoked_at": datetime.now(timezone.utc).isoformat(), "revoke_reason": req.reason}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="License key tidak ditemukan")
    logger.warning(f"REVOKED license {req.license_key} — reason: {req.reason}")
    return {"ok": True, "message": f"License {req.license_key} dicabut"}


# ── GET / (health check) ───────────────────────────────────────────────────────
@app.get("/")
async def health():
    return {
        "service": "NOC License Server",
        "vendor":  "ARBA Training",
        "status":  "running",
        "time":    datetime.now(timezone.utc).isoformat(),
    }


# ── Helper ─────────────────────────────────────────────────────────────────────
def _safe_hostname(hostname: str) -> str:
    """Buat hostname safe untuk MongoDB field key."""
    return hostname.replace(".", "_").replace("$", "").replace(" ", "_")[:64]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
