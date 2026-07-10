"""
qris_hub.py — Central QRIS Hub Router
=======================================
POST /qris/generate   — Dari NOC Billing Pro: buat QRIS
GET  /qris/status/{id} — Cek status transaksi
POST /qris/callback   — Dari BRI: payment notification
POST /qris/admin/test — Test koneksi BRI (admin only)
GET  /qris/admin/transactions — Semua transaksi cross-tenant (admin)
GET  /qris/admin/wallets      — Semua wallet tenant (admin)
POST /qris/admin/withdrawals/{id}/process — Approve/reject withdrawal
"""

import os
import uuid
import hmac
import hashlib
import json
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import pymongo

from auth import require_admin
from models import (
    QrisGenerateRequest,
    AutoRegisterCallbackRequest,
    WithdrawalRequest,
    BankAccountUpdate,
)
import bri_qris
import bri_payout

router = APIRouter()

# ── DB Setup — Gunakan connection pool dari main.py (shared, bukan buat baru) ──
# Ini mencegah tiga connection pool terpisah (main, qris_hub, bri_qris)
import asyncio as _asyncio

mongo_uri = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017/"
db_name   = os.environ.get("MONGO_DB_NAME") or os.environ.get("DB_NAME", "noc_license_server")

# Coba import shared client dari main; fallback buat sendiri jika diimport sebelum main init
try:
    from __main__ import client as _main_client
    _mongo_client = _main_client
except Exception:
    _mongo_client = pymongo.MongoClient(
        mongo_uri,
        maxPoolSize=50,
        minPoolSize=5,
        maxIdleTimeMS=30000,
        serverSelectionTimeoutMS=5000,
    )

db = _mongo_client[db_name]

c_licenses  = db["license_keys"]
c_clients   = db["license_clients"]
c_txs       = db["qris_transactions"]
c_wallets   = db["qris_wallets"]
c_wds       = db["qris_withdrawals"]
c_settings  = db["system_settings"]

# ── Helper: jalankan operasi pymongo (sync) di thread pool ─────────────────────
# Mencegah blocking event loop FastAPI saat load tinggi
async def _run_sync(func, *args, **kwargs):
    """Jalankan fungsi sync pymongo di executor agar non-blocking."""
    loop = _asyncio.get_event_loop()
    import functools
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

from scheduler import _send_fonnte

async def _notify_wd_status(client_id: str, status_msg: str, wd: dict):
    client = c_clients.find_one({"id": client_id})
    if not client or not client.get("phone"): return
    st = c_settings.find_one({"id": "sys_prefs"}) or {}
    wa_enabled = st.get("wa_gateway_enabled", False)
    wa_token = st.get("wa_fonnte_token", "")
    if not wa_enabled or not wa_token: return
    
    msg = (
        f"💳 *Info Penarikan Dana*\n\n"
        f"Halo {client.get('name')},\n"
        f"Status penarikan Anda sebesar *Rp {wd.get('amount'):,}* saat ini:\n\n"
        f"👉 *{status_msg}*\n\n"
    )
    if wd.get("notes"):
        msg += f"Catatan: {wd.get('notes')}\n\n"
    msg += "Terima kasih."
    
    await _send_fonnte(wa_token, client.get("phone"), msg, st.get("wa_fonnte_sender", ""), st.get("wa_fonnte_device", ""))


# ── Indexes ────────────────────────────────────────────────────────────────────
try:
    c_txs.create_index("partner_reference_no", unique=True)
    c_txs.create_index([("client_id", 1), ("created_at", -1)])
    c_wallets.create_index("client_id", unique=True)
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _fmt_rp(amount: int) -> str:
    return f"Rp {amount:,}".replace(",", ".")

def _verify_license_key(license_key: str) -> dict:
    """Verify license key dan return client doc (sync — panggil via _run_sync di async context)."""
    lic = c_licenses.find_one({"license_key": license_key, "is_active": True})
    if not lic:
        raise HTTPException(403, "License key tidak valid atau tidak aktif.")
    now_iso = _now()
    if lic.get("expires_at", "") < now_iso:
        raise HTTPException(403, "License key sudah kadaluarsa.")
    client = c_clients.find_one({"id": lic["client_id"]})
    if not client:
        raise HTTPException(403, "Client tidak ditemukan untuk license key ini.")
    return client

async def _verify_license_key_async(license_key: str) -> dict:
    """Async wrapper untuk _verify_license_key — non-blocking."""
    return await _run_sync(_verify_license_key, license_key)

def _get_or_create_wallet(client_id: str) -> dict:
    """Get wallet, create if not exists."""
    wallet = c_wallets.find_one({"client_id": client_id})
    if not wallet:
        wallet = {
            "client_id": client_id,
            "balance": 0,
            "pending_withdrawal": 0,
            "total_credited": 0,
            "total_withdrawn": 0,
            "total_transactions": 0,
            "updated_at": _now()
        }
        c_wallets.insert_one(wallet)
    return wallet

def _build_partner_ref(client: dict, invoice_number: str) -> str:
    """Build unique partner reference number.
    Format: CLT{seq}-{invoice}-{ts5}
    Max 64 char (BRI limit).
    """
    seq = client.get("tenant_seq", client["id"][:6].upper())
    ts  = str(int(datetime.now(timezone.utc).timestamp()))[-6:]
    inv = invoice_number.replace("-", "")[:12]
    return f"{seq}-{inv}-{ts}"

def _make_callback_hmac(payload: dict, secret: str) -> str:
    """Generate HMAC-SHA256 untuk forward callback ke tenant."""
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

import time
_qris_rate_limits = {}
RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW = 60

def _check_qris_rate_limit(license_key: str):
    now = time.time()
    record = _qris_rate_limits.get(license_key)
    if not record or now > record["reset_at"]:
        _qris_rate_limits[license_key] = {"count": 1, "reset_at": now + RATE_LIMIT_WINDOW}
        return
    if record["count"] >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Terlalu banyak permintaan QRIS. Silakan coba lagi nanti.")
    record["count"] += 1


# ══════════════════════════════════════════════════════════════════════════════
# TENANT ENDPOINTS — dipanggil oleh NOC Billing Pro
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/auto-register-callback")
async def auto_register_callback(req: AutoRegisterCallbackRequest):
    """Menerima pendaftaran otomatis callback url dan secret dari NOC Billing client."""
    client = await _verify_license_key_async(req.license_key)
    client_id = client["id"]
    
    # Update dokumen klien di database
    await _run_sync(
        c_clients.update_one,
        {"id": client_id},
        {"$set": {
            "callback_url": req.callback_url,
            "callback_secret": req.callback_secret,
            "updated_at": _now()
        }}
    )
    return {"status": "success", "message": "Callback config registered successfully."}


@router.post("/generate")
async def generate_qris_endpoint(req: QrisGenerateRequest, request: Request):
    """Generate QRIS MPM Dynamic untuk invoice dari NOC Billing Pro.

    Semua operasi DB dijalankan via _run_sync() agar non-blocking di event loop.
    """
    import random

    # 1. Rate limit + Verify license key (async — non-blocking)
    _check_qris_rate_limit(req.license_key)
    client = await _verify_license_key_async(req.license_key)
    client_id = client["id"]

    qris_gateway = client.get("qris_gateway")
    if not qris_gateway:
        raise HTTPException(
            status_code=403,
            detail="QRIS Bersama masih menunggu persetujuan Admin. Hubungi pihak License Server."
        )

    # 2. Kalkulasi Fee & Kode Unik
    original_amount  = req.amount
    fee_qris_percent = float(client.get("fee_qris_percent", 0.0))
    fee_qris_amount  = int(original_amount * (fee_qris_percent / 100))
    use_unique_code  = client.get("use_unique_code", False)
    unique_code      = random.randint(1, 999) if use_unique_code else 0
    final_amount     = original_amount + fee_qris_amount + unique_code

    # 3. Cek transaksi pending yang sama (async)
    existing = await _run_sync(
        c_txs.find_one,
        {"client_id": client_id, "noc_invoice_number": req.invoice_number, "status": "pending"}
    )
    if existing:
        return {
            "tx_id":          existing["id"],
            "qr_content":     existing.get("qr_content", ""),
            "qr_url":         existing.get("qr_url", ""),
            "partner_ref_no": existing["partner_reference_no"],
            "expires_at":     existing["expires_at"],
            "reused":         True,
        }

    # 4. Build partner reference number
    partner_ref = _build_partner_ref(client, req.invoice_number)
    tx_id       = str(uuid.uuid4())
    now         = _now()
    expires_at  = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat()

    # 5. Call QRIS API (BNI or BRI based on qris_gateway)
    import bni_qris
    import bri_qris
    try:
        if qris_gateway == "bni":
            qris_result = await bni_qris.generate_qris(
                partner_ref_no=partner_ref,
                amount=final_amount,
            )
        else:
            qris_result = await bri_qris.generate_qris(
                partner_ref_no=partner_ref,
                amount=final_amount,
            )
    except Exception as e:
        await _run_sync(c_txs.insert_one, {
            "id":                  tx_id,
            "client_id":           client_id,
            "tenant_seq":          client.get("tenant_seq", ""),
            "partner_reference_no": partner_ref,
            "noc_invoice_number":  req.invoice_number,
            "customer_name":       req.customer_name,
            "amount":              final_amount,
            "original_amount":     original_amount,
            "fee_qris_amount":     fee_qris_amount,
            "unique_code":         unique_code,
            "callback_url":        req.callback_url,
            "status":              "failed",
            "error":               str(e),
            "created_at":          now,
            "expires_at":          expires_at,
        })
        raise HTTPException(502, f"Gagal generate QRIS dari BRI: {str(e)}")

    # 6. Simpan transaksi sukses (async)
    await _run_sync(c_txs.insert_one, {
        "id":                  tx_id,
        "client_id":           client_id,
        "tenant_seq":          client.get("tenant_seq", ""),
        "partner_reference_no": partner_ref,
        "gateway_provider":    qris_gateway,
        "gateway_ref_no":      qris_result.get("ref_no", ""),
        "noc_invoice_number":  req.invoice_number,
        "customer_name":       req.customer_name,
        "amount":              final_amount,
        "original_amount":     original_amount,
        "fee_qris_amount":     fee_qris_amount,
        "unique_code":         unique_code,
        "qr_content":          qris_result.get("qr_content", ""),
        "qr_url":              qris_result.get("qr_url", ""),
        "callback_url":        req.callback_url,
        "status":              "pending",
        "paid_at":             None,
        "forwarded":           False,
        "forwarded_at":        None,
        "forwarded_status":    None,
        "created_at":          now,
        "expires_at":          expires_at,
    })

    return {
        "tx_id":          tx_id,
        "qr_content":     qris_result.get("qr_content", ""),
        "qr_url":         qris_result.get("qr_url", ""),
        "partner_ref_no": partner_ref,
        "expires_at":     expires_at,
        "reused":         False,
    }


@router.get("/status/{tx_id}")
async def get_qris_status(tx_id: str):
    """Cek status transaksi QRIS by tx_id (dipanggil NOC Billing Pro)."""
    tx = await _run_sync(c_txs.find_one, {"id": tx_id}, {"_id": 0, "qr_content": 0})
    if not tx:
        raise HTTPException(404, "Transaksi tidak ditemukan")
    return {
        "tx_id":               tx_id,
        "status":              tx.get("status", "unknown"),
        "amount":              tx.get("amount", 0),
        "original_amount":     tx.get("original_amount", tx.get("amount", 0)),
        "paid_at":             tx.get("paid_at"),
        "noc_invoice_number":  tx.get("noc_invoice_number"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BNI CALLBACK — dipanggil oleh BNI saat pembayaran berhasil
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/callback/bni")
async def bni_qris_callback(request: Request, background_tasks: BackgroundTasks):
    """Menerima notifikasi payment dari BNI SNAP API."""
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")

    x_signature = request.headers.get("X-SIGNATURE")
    x_timestamp = request.headers.get("X-TIMESTAMP")
    
    c_settings = db["system_settings"]
    st = c_settings.find_one({"id": "sys_prefs"}) or {}
    client_secret = st.get("bni_client_secret", "")
    
    if client_secret:
        if not x_signature or not x_timestamp:
            raise HTTPException(401, "Missing signature headers")
        import bni_qris
        
        try:
            from field_crypto import decrypt_field
            client_secret = decrypt_field(client_secret)
        except ImportError:
            pass

        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip() if "Bearer " in auth_header else ""

        if not bni_qris.verify_callback_signature(
            request.method, request.url.path, token, body_str, x_timestamp, client_secret, x_signature
        ):
            # Coba tanpa path jika BNI tidak me-require path di symmetric signature webhook
            if not bni_qris.verify_callback_signature(
                request.method, "", token, body_str, x_timestamp, client_secret, x_signature
            ):
                raise HTTPException(401, "Invalid signature")

    try:
        payload = json.loads(body_str)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    partner_ref_no = payload.get("originalPartnerReferenceNo") or payload.get("partnerReferenceNo", "")
    response_code  = payload.get("responseCode", "")
    amount_obj     = payload.get("amount", {})
    amount_val     = int(float(amount_obj.get("value", "0"))) if amount_obj else 0
    bni_trx_id     = payload.get("referenceNo", "")

    tx = c_txs.find_one({"partner_reference_no": partner_ref_no})
    if not tx:
        return {"responseCode": "2007300", "responseMessage": "Successful"}

    if tx.get("status") == "paid":
        return {"responseCode": "2007300", "responseMessage": "Already processed"}

    paid = response_code in ("2007300", "00", "0", "2002700")

    if paid:
        now = _now()
        c_txs.update_one(
            {"partner_reference_no": partner_ref_no},
            {"$set": {
                "status": "paid",
                "paid_at": now,
                "gateway_trx_id": bni_trx_id,
                "callback_raw": payload
            }}
        )

        background_tasks.add_task(
            _credit_wallet_and_forward,
            tx["client_id"], tx["id"], amount_val,
            tx.get("callback_url", ""), tx.get("noc_invoice_number", ""),
            tx.get("original_amount", tx.get("amount", amount_val))
        )
    else:
        c_txs.update_one(
            {"partner_reference_no": partner_ref_no},
            {"$set": {"status": "failed", "callback_raw": payload}}
        )

    return {"responseCode": "2007300", "responseMessage": "Successful"}


# ══════════════════════════════════════════════════════════════════════════════
# BRI CALLBACK — dipanggil oleh BRI saat pembayaran berhasil
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/callback")
async def bri_qris_callback(request: Request, background_tasks: BackgroundTasks):
    """Menerima notifikasi payment dari BRI SNAP API.
    
    BRI mengirim callback dengan header X-SIGNATURE untuk verifikasi.
    Setelah verifikasi, update transaksi, credit wallet, forward ke tenant.
    """
    raw_body = await request.body()
    body_str = raw_body.decode("utf-8")

    # Verify signature from BRI
    x_signature = request.headers.get("X-SIGNATURE")
    x_timestamp = request.headers.get("X-TIMESTAMP")
    
    c_settings = db["system_settings"]
    st = c_settings.find_one({"id": "sys_prefs"}) or {}
    client_secret = st.get("bri_client_secret", "")
    
    if client_secret:
        if not x_signature or not x_timestamp:
            raise HTTPException(401, "Missing signature headers")
        from bri_qris import verify_callback_signature
        if not verify_callback_signature(client_secret, x_signature, x_timestamp, body_str):
            raise HTTPException(401, "Invalid signature")

    # Parse body
    try:
        payload = json.loads(body_str)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Extract fields dari BRI callback
    partner_ref_no = payload.get("originalPartnerReferenceNo") or payload.get("partnerReferenceNo", "")
    response_code  = payload.get("responseCode", "")
    amount_obj     = payload.get("amount", {})
    amount_val     = int(float(amount_obj.get("value", "0"))) if amount_obj else 0
    bri_trx_id     = payload.get("referenceNo", "")

    # Cari transaksi
    tx = c_txs.find_one({"partner_reference_no": partner_ref_no})
    if not tx:
        # BRI bisa kirim callback walau transaksi tidak ada di kita — return 200
        return {"responseCode": "2007300", "responseMessage": "Successful"}

    # Jika sudah paid, idempotent
    if tx.get("status") == "paid":
        return {"responseCode": "2007300", "responseMessage": "Already processed"}

    # responseCode "2007300" = sukses, "4007300" = gagal
    paid = response_code in ("2007300", "00", "0")

    if paid:
        now = _now()
        # Update transaksi → paid
        c_txs.update_one(
            {"partner_reference_no": partner_ref_no},
            {"$set": {
                "status": "paid",
                "paid_at": now,
                "bri_trx_id": bri_trx_id,
                "callback_raw": payload
            }}
        )

        # Credit wallet tenant (background task) - Bagian 4
        background_tasks.add_task(
            _credit_wallet_and_forward,
            tx["client_id"], tx["id"], amount_val,
            tx.get("callback_url", ""), tx.get("noc_invoice_number", ""),
            tx.get("original_amount", tx.get("amount", amount_val))
        )
    else:
        c_txs.update_one(
            {"partner_reference_no": partner_ref_no},
            {"$set": {"status": "failed", "callback_raw": payload}}
        )

    return {"responseCode": "2007300", "responseMessage": "Successful"}


async def _credit_wallet_and_forward(
    client_id: str, tx_id: str, amount: int,
    callback_url: str, invoice_number: str, original_amount: int
):
    """Background task: credit wallet + forward callback ke tenant NOC Billing Pro."""

    # 1. Credit wallet - Bagian 4: Masuk ke revenue_balance
    c_wallets.update_one(
        {"client_id": client_id},
        {
            "$inc": {
                "revenue_balance": original_amount,
                "total_credited": original_amount,
                "total_transactions": 1
            },
            "$set": {"updated_at": _now()},
            "$setOnInsert": {"hold_balance": 0}
        },
        upsert=True
    )

    # 2. Get client untuk callback secret
    client = c_clients.find_one({"id": client_id})
    callback_secret = (client or {}).get("callback_secret", "")

    # 3. Forward callback ke NOC Billing Pro
    if callback_url:
        forward_payload = {
            "tx_id": tx_id,
            "invoice_number": invoice_number,
            "amount": original_amount,
            "status": "paid",
            "paid_at": _now(),
            "source": "central_qris"
        }
        hmac_sig = _make_callback_hmac(forward_payload, callback_secret) if callback_secret else ""
        headers = {
            "Content-Type": "application/json",
            "X-QRIS-SIGNATURE": hmac_sig,
            "X-QRIS-SOURCE": "license.arbatraining.com"
        }
        try:
            async with httpx.AsyncClient(timeout=15) as hc:
                resp = await hc.post(callback_url, json=forward_payload, headers=headers)
                c_txs.update_one(
                    {"id": tx_id},
                    {"$set": {
                        "forwarded": True,
                        "forwarded_at": _now(),
                        "forwarded_status": resp.status_code
                    }}
                )
        except Exception as e:
            c_txs.update_one(
                {"id": tx_id},
                {"$set": {"forwarded": False, "forward_error": str(e)}}
            )

    # 4. Fire Webhook ke tenant (jika ada webhook_url tersendiri di profil klien)
    # Bagian 11: Webhook Notifikasi ke Tenant
    client = c_clients.find_one({"id": client_id}) or {}
    webhook_url = client.get("webhook_url", "")
    webhook_secret = client.get("webhook_secret", "")
    if webhook_url and webhook_url != callback_url:
        webhook_payload = {
            "event": "payment.received",
            "tx_id": tx_id,
            "client_id": client_id,
            "invoice_number": invoice_number,
            "amount": original_amount,
            "status": "paid",
            "paid_at": _now()
        }
        sig = _make_callback_hmac(webhook_payload, webhook_secret) if webhook_secret else ""
        try:
            async with httpx.AsyncClient(timeout=10) as hc:
                await hc.post(webhook_url, json=webhook_payload, headers={
                    "Content-Type": "application/json",
                    "X-WEBHOOK-SIGNATURE": sig,
                    "X-WEBHOOK-EVENT": "payment.received",
                    "X-WEBHOOK-SOURCE": "noc-license-server"
                })
        except Exception as e:
            print(f"[Webhook] Gagal kirim ke {webhook_url}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/admin/test-connection")
async def admin_test_connection(gateway: str = "bri", admin: str = Depends(require_admin)):
    """Test koneksi ke QRIS SNAP API.
    
    Query parameter:
        gateway (str): 'bri' (default) atau 'bni'
    
    Contoh:
        POST /qris/admin/test-connection?gateway=bni
        POST /qris/admin/test-connection?gateway=bri
    """
    gw = (gateway or "bri").lower().strip()
    if gw == "bni":
        import bni_qris
        result = await bni_qris.test_connection()
    else:
        result = await bri_qris.test_connection()
    return result


@router.get("/admin/transactions")
def admin_list_transactions(
    limit: int = 100, skip: int = 0,
    client_id: str = None, status: str = None,
    admin: str = Depends(require_admin)
):
    """List semua transaksi QRIS cross-tenant."""
    query = {}
    if client_id:
        query["client_id"] = client_id
    if status:
        query["status"] = status

    txs = list(c_txs.find(query, {"_id": 0, "qr_content": 0, "callback_raw": 0})
               .sort("created_at", -1).skip(skip).limit(limit))
    total = c_txs.count_documents(query)

    # Attach client name
    for tx in txs:
        cl = c_clients.find_one({"id": tx.get("client_id")})
        tx["client_name"] = (cl or {}).get("name", "-")

    return {"transactions": txs, "total": total}


@router.post("/admin/transactions/{tx_id}/check")
async def admin_check_transaction(tx_id: str, admin: str = Depends(require_admin)):
    """Manual check status transaksi QRIS ke API provider (BNI/BRI).
    Membaca field gateway_provider dari transaksi untuk memilih gateway yang tepat.
    """
    tx = c_txs.find_one({"id": tx_id})
    if not tx:
        raise HTTPException(404, "Transaksi tidak ditemukan")
    
    partner_ref = tx.get("partner_reference_no")
    if not partner_ref:
        raise HTTPException(400, "Transaksi tidak memiliki partner_reference_no")
    
    # Tentukan gateway berdasarkan data transaksi (bukan selalu BRI)
    gateway_provider = tx.get("gateway_provider", "bri").lower()
        
    try:
        if gateway_provider == "bni":
            import bni_qris
            status = await bni_qris.query_qris_status(partner_ref)
        else:
            import bri_qris
            status = await bri_qris.query_qris_status(partner_ref)
        
        code = status.get('responseCode', 'N/A')
        msg  = status.get('responseMessage', 'N/A')
        trx_status = status.get('transactionStatus', status.get('status', ''))
        
        # Jika berhasil dibayar di sistem provider tapi lokal belum
        if (code in ['2005100', '200', '2007300'] or trx_status in ['SUCCESS', 'PAID', '00', 'settlement']) and tx.get("status") != "paid":
            # Update lokal menjadi PAID
            c_txs.update_one(
                {"id": tx_id},
                {"$set": {"status": "paid", "paid_at": _now(), "callback_raw": status}}
            )
            # Jalankan forward/webhook
            await _credit_wallet_and_forward(
                tx["client_id"], tx_id, tx["amount"],
                tx.get("callback_url"), tx.get("noc_invoice_number"), tx.get("original_amount")
            )
            return {"status": "success", "message": f"Status diperbarui menjadi PAID dari {gateway_provider.upper()}"}
            
        return {"status": "success", "message": f"[{gateway_provider.upper()}] Status saat ini di provider: {msg} / {trx_status}", "raw": status}
        
    except Exception as e:
        raise HTTPException(502, f"Gagal cek status ke provider {gateway_provider.upper()}: {str(e)}")


@router.get("/admin/wallets")
def admin_list_wallets(admin: str = Depends(require_admin)):
    """List semua wallet tenant dengan detail client."""
    wallets = list(c_wallets.find({}, {"_id": 0}))
    for w in wallets:
        cl = c_clients.find_one({"id": w.get("client_id")})
        w["client_name"] = (cl or {}).get("name", "-")
        w["client_email"] = (cl or {}).get("email", "-")
    return {"wallets": wallets, "total": len(wallets)}


@router.get("/admin/withdrawals")
def admin_list_withdrawals(status: str = None, admin: str = Depends(require_admin)):
    """List semua withdrawal request dari semua tenant."""
    query = {}
    if status:
        query["status"] = status
    wds = list(c_wds.find(query, {"_id": 0}).sort("requested_at", -1))
    for w in wds:
        cl = c_clients.find_one({"id": w.get("client_id")})
        w["client_name"] = (cl or {}).get("name", "-")
    return {"withdrawals": wds, "total": len(wds)}


@router.post("/admin/withdrawals/{wd_id}/approve")
async def admin_approve_withdrawal(wd_id: str, admin: str = Depends(require_admin)):
    """Approve withdrawal request → status: processing."""
    wd = c_wds.find_one({"id": wd_id})
    if not wd:
        raise HTTPException(404, "Withdrawal tidak ditemukan")
    if wd["status"] != "pending":
        raise HTTPException(400, f"Status saat ini: {wd['status']}. Hanya 'pending' yang bisa di-approve.")

    c_wds.update_one({"id": wd_id}, {"$set": {
        "status": "processing",
        "processed_by": admin,
        "processed_at": _now()
    }})
    await _notify_wd_status(wd["client_id"], "DIPROSES (Menunggu Transfer)", wd)
    return {"message": "Withdrawal di-approve, status → processing"}


class CompletePayload(BaseModel):
    actual_transfer_fee: Optional[int] = None

@router.post("/admin/withdrawals/{wd_id}/complete")
async def admin_complete_withdrawal(wd_id: str, payload: CompletePayload, admin: str = Depends(require_admin)):
    """Mark withdrawal sebagai selesai → deduct wallet balance."""
    wd = c_wds.find_one({"id": wd_id})
    if not wd:
        raise HTTPException(404, "Withdrawal tidak ditemukan")
    if wd["status"] != "processing":
        raise HTTPException(400, "Hanya withdrawal 'processing' yang bisa diselesaikan.")

    # Deduct dari wallet sesuai mekanisme baru (revenue_balance & hold_balance)
    wallet = c_wallets.find_one({"client_id": wd["client_id"]})
    if not wallet:
        raise HTTPException(404, "Wallet tidak ditemukan")
        
    req_amount = wd["amount"]
    topup_hold = wd.get("topup_hold", 0)
    
    # Gunakan actual_transfer_fee jika diberikan oleh admin, fallback ke prediksi awal
    transfer_fee = payload.actual_transfer_fee if payload.actual_transfer_fee is not None else wd.get("transfer_fee", 0)
    
    total_deduction_from_revenue = req_amount + topup_hold

    # === Coba eksekusi transfer via BRIAPI (jika dikonfigurasi) ===
    payout_result = None
    if bri_payout.is_payout_configured():
        payout_result = await bri_payout.execute_bri_transfer(
            bank_name=wd.get("bank_name", ""),
            account_number=wd.get("account_number", ""),
            account_holder=wd.get("account_holder", ""),
            amount=req_amount,
            notes=f"Payout withdrawal #{wd_id}",
            wd_id=wd_id,
        )
        if not payout_result["success"]:
            raise HTTPException(502, f"Transfer BRIAPI gagal: {payout_result['message']}")

    # Potong saldo wallet
    c_wallets.update_one({"client_id": wd["client_id"]}, {
        "$inc": {
            "balance": -req_amount,
            "revenue_balance": -total_deduction_from_revenue,
            "hold_balance": topup_hold - transfer_fee,
            "total_withdrawn": req_amount,
            "pending_withdrawal": -total_deduction_from_revenue
        },
        "$set": {"updated_at": _now()}
    })
    c_wds.update_one({"id": wd_id}, {"$set": {
        "status": "completed",
        "completed_at": _now(),
        "completed_by": admin,
        "actual_transfer_fee": transfer_fee,
        "payout_reference": payout_result["reference_no"] if payout_result else None,
        "payout_mode": "auto" if payout_result else "manual",
    }})
    await _notify_wd_status(wd["client_id"], "SELESAI (Dana Telah Ditransfer)", wd)
    ref_info = f" Ref BRI: {payout_result['reference_no']}" if payout_result else ""
    return {"message": f"Withdrawal selesai. Saldo wallet sudah dipotong.{ref_info}"}


class RejectPayload(BaseModel):
    notes: str = ""

@router.post("/admin/withdrawals/{wd_id}/reject")
async def admin_reject_withdrawal(wd_id: str, payload: RejectPayload, admin: str = Depends(require_admin)):
    """Reject withdrawal request."""
    wd = c_wds.find_one({"id": wd_id})
    if not wd:
        raise HTTPException(404, "Withdrawal tidak ditemukan")
    if wd["status"] not in ("pending", "processing"):
        raise HTTPException(400, "Withdrawal sudah final.")

    # Kembalikan pending_withdrawal ke wallet
    req_amount = wd["amount"]
    topup_hold = wd.get("topup_hold", 0)
    total_pending = req_amount + topup_hold

    c_wallets.update_one({"client_id": wd["client_id"]}, {
        "$inc": {"pending_withdrawal": -total_pending},
        "$set": {"updated_at": _now()}
    })
    
    notes = payload.notes
    c_wds.update_one({"id": wd_id}, {"$set": {
        "status": "rejected",
        "notes": notes,
        "rejected_by": admin,
        "rejected_at": _now()
    }})
    wd["notes"] = notes
    await _notify_wd_status(wd["client_id"], "DITOLAK", wd)
    return {"message": "Withdrawal ditolak."}
