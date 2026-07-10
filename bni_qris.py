"""
bni_qris.py — BNI SNAP API Client for QRIS MPM Dynamic
========================================================
- OAuth 2.0 B2B (Client Credentials Grant)
- Asymmetric Signature: RSA-SHA256 (untuk access token)
- Symmetric Signature: HMAC-SHA512 (untuk API calls)
- QRIS MPM Generate, Query Status
"""

import os
import json
import hashlib
import hmac
import base64
import uuid
from datetime import datetime, timezone
import httpx
import pymongo

# Dekripsi field sensitif yang tersimpan dalam format enc:v1:... di MongoDB
try:
    from field_crypto import decrypt_field
except ImportError:
    def decrypt_field(v): return v  # fallback jika modul belum ada

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ── DB Setup ───────────────────────────────────────────────────────────────────
mongo_uri = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017/"
db_name = os.environ.get("MONGO_DB_NAME") or os.environ.get("DB_NAME", "noc_license_server")
_mongo_client = pymongo.MongoClient(mongo_uri)
db = _mongo_client[db_name]


def _get_bni_config() -> dict:
    """Ambil BNI QRIS config dari system_settings.
    
    PENTING: Field sensitif (client_secret, private_key_pem) dienkripsi saat disimpan
    menggunakan AES-256-GCM oleh settings.py. Harus didekripsi di sini sebelum digunakan
    untuk request ke SNAP API BNI.
    """
    doc = db["system_settings"].find_one({"id": "sys_prefs"}) or {}
    return {
        "client_id": doc.get("bni_client_id", ""),
        # decrypt_field: kembalikan nilai asli jika terenkripsi (format enc:v1:...)
        # Jika tidak terenkripsi (plain-text / data lama), dikembalikan apa adanya.
        "client_secret": decrypt_field(doc.get("bni_client_secret", "")),
        "private_key_pem": decrypt_field(doc.get("bni_private_key_pem", "")),
        # BNI: client_id juga berfungsi sebagai X-PARTNER-ID
        "sandbox": doc.get("bni_qris_sandbox", True),  # Independent sandbox toggle
        # Flag aktif/nonaktif dari toggle admin UI — WAJIB dicek sebelum generate QRIS
        "enabled": doc.get("bni_qris_enabled", False),
    }


def _get_base_url(config: dict) -> str:
    # URL BNI SNAP API 
    if config.get("sandbox"):
        return "https://apidev.bni.co.id"
    return "https://api.bni.co.id"


def _get_timestamp() -> str:
    """ISO 8601 timestamp: 2026-05-14T12:00:00.000+07:00"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


# ══════════════════════════════════════════════════════════════════════════════
# SIGNATURES
# ══════════════════════════════════════════════════════════════════════════════

def generate_asymmetric_signature(client_id: str, private_key_pem: str, timestamp: str) -> str:
    if not HAS_CRYPTO:
        raise RuntimeError("Package 'cryptography' diperlukan. Install: pip install cryptography")

    string_to_sign = f"{client_id}|{timestamp}"
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"), password=None
    )
    signature = private_key.sign(
        string_to_sign.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")


def generate_symmetric_signature(
    http_method: str, url_path: str, access_token: str,
    request_body: str, timestamp: str, client_secret: str
) -> str:
    body_hash = hashlib.sha256(request_body.encode("utf-8")).hexdigest().lower()
    string_to_sign = f"{http_method}:{url_path}:{access_token}:{body_hash}:{timestamp}"
    signature = hmac.new(
        client_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha512
    ).digest()
    return base64.b64encode(signature).decode("utf-8")


def verify_callback_signature(
    http_method: str, url_path: str, access_token: str,
    request_body: str, timestamp: str, client_secret: str,
    received_signature: str
) -> bool:
    expected = generate_symmetric_signature(
        http_method, url_path, access_token, request_body, timestamp, client_secret
    )
    return hmac.compare_digest(expected, received_signature)


# ══════════════════════════════════════════════════════════════════════════════
# API CALLS
# ══════════════════════════════════════════════════════════════════════════════

_access_token_cache = {"token": "", "expires_at": ""}
_token_lock = None

def _get_token_lock():
    global _token_lock
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if _token_lock is None:
            _token_lock = asyncio.Lock()
    except RuntimeError:
        _token_lock = asyncio.Lock()
    return _token_lock


async def get_access_token(config: dict = None) -> str:
    if not config:
        config = _get_bni_config()

    if (_access_token_cache["token"] and
            _access_token_cache["expires_at"] > datetime.now(timezone.utc).isoformat()):
        return _access_token_cache["token"]

    async with _get_token_lock():
        if (_access_token_cache["token"] and
                _access_token_cache["expires_at"] > datetime.now(timezone.utc).isoformat()):
            return _access_token_cache["token"]

        base_url  = _get_base_url(config)
        timestamp = _get_timestamp()
        signature = generate_asymmetric_signature(
            config["client_id"], config["private_key_pem"], timestamp
        )

        headers = {
            "Content-Type":  "application/json",
            "X-CLIENT-KEY":  config["client_id"],
            "X-TIMESTAMP":   timestamp,
            "X-SIGNATURE":   signature,
        }
        body = {"grantType": "client_credentials"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/snap/v1.0/access-token/b2b",
                headers=headers,
                json=body,
            )
            data = resp.json()

        if resp.status_code != 200 or not data.get("accessToken"):
            raise Exception(f"BNI OAuth failed: {data}")

        _access_token_cache["token"] = data["accessToken"]
        from datetime import timedelta
        _access_token_cache["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expiresIn", 900)) - 60)
        ).isoformat()

        return _access_token_cache["token"]


async def generate_qris(
    partner_ref_no: str,
    amount: int,
    validity_seconds: int = 600,
    config: dict = None
) -> dict:
    if not config:
        config = _get_bni_config()

    # Guard: tolak jika BNI QRIS belum diaktifkan oleh admin
    if not config.get("enabled"):
        raise Exception("BNI QRIS belum diaktifkan. Aktifkan toggle BNI SNAP di Pengaturan Payment Gateway.")

    access_token = await get_access_token(config)
    base_url = _get_base_url(config)
    timestamp = _get_timestamp()
    url_path = "/snap/v1.0/qr/qr-mpm-generate"
    external_id = str(uuid.uuid4())

    body = {
        "partnerReferenceNo": partner_ref_no,
        "amount": {"value": f"{amount}.00", "currency": "IDR"},
        "merchantId": config["client_id"], # Usually same as client_id for BNI
        "terminalId": "TERM01",
        "validityPeriod": f"{validity_seconds}",
    }

    body_str = json.dumps(body, separators=(',', ':'))
    signature = generate_symmetric_signature(
        "POST", url_path, access_token, body_str, timestamp, config["client_secret"]
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
        "X-PARTNER-ID": config["client_id"],
        "X-EXTERNAL-ID": external_id,
        "CHANNEL-ID": "QRI",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}{url_path}", headers=headers, content=body_str)
        data = resp.json()

    response_code = data.get("responseCode", "")
    if response_code != "2004700" and resp.status_code not in (200, 201):
        raise Exception(f"BNI QRIS generate failed: {data}")

    return {
        "qr_content": data.get("qrContent", ""),
        "qr_url": data.get("qrUrl", ""),
        "ref_no": data.get("referenceNo", ""),
        "partner_ref_no": partner_ref_no,
        "raw": data
    }


async def test_connection() -> dict:
    """Test BNI API connection (get access token)."""
    try:
        config = _get_bni_config()
        if not config["client_id"] or not config["client_secret"]:
            return {"success": False, "message": "Client ID atau Client Secret BNI belum diisi."}
        if not config["private_key_pem"]:
            return {"success": False, "message": "Private Key PEM BNI belum diisi."}
        token = await get_access_token(config)
        return {"success": True, "message": f"Koneksi BNI berhasil! Token: {token[:20]}..."}
    except Exception as e:
        return {"success": False, "message": f"Gagal terkoneksi ke BNI: {str(e)}"}
