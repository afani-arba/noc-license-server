"""
bri_qris.py — BRI SNAP API Client for QRIS MPM Dynamic
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

# Opsional: cryptography untuk RSA
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


def _get_bri_config() -> dict:
    """Ambil BRI QRIS config dari system_settings.
    
    PENTING: Field sensitif (client_secret, private_key_pem) dienkripsi saat disimpan
    menggunakan AES-256-GCM oleh settings.py. Harus didekripsi di sini sebelum digunakan
    untuk request ke SNAP API BRI.
    """
    doc = db["system_settings"].find_one({"id": "sys_prefs"}) or {}
    return {
        "client_id": doc.get("bri_client_id", ""),
        # decrypt_field: kembalikan nilai asli jika terenkripsi (format enc:v1:...)
        # Jika tidak terenkripsi (plain-text / data lama), dikembalikan apa adanya.
        "client_secret": decrypt_field(doc.get("bri_client_secret", "")),
        "partner_id": doc.get("bri_partner_id", ""),
        "private_key_pem": decrypt_field(doc.get("bri_private_key_pem", "")),
        "enabled": doc.get("bri_qris_enabled", False),
        "sandbox": doc.get("bri_qris_sandbox", True),
        "merchant_name": doc.get("bri_merchant_name", "NOC License Server"),
        "merchant_city": doc.get("bri_merchant_city", "Jakarta"),
        # merchant_id: ID Merchant khusus dari BRI — wajib untuk generate QRIS
        # Fallback ke partner_id jika belum diisi (kompatibilitas data lama)
        "merchant_id": doc.get("bri_merchant_id", "") or doc.get("bri_partner_id", ""),
        # terminal_id: ID Terminal per sistem/lokasi, default TERM01
        "terminal_id": doc.get("bri_terminal_id", "TERM01") or "TERM01",
    }


def _get_base_url(config: dict) -> str:
    if config.get("sandbox"):
        return "https://sandbox.partner.api.bri.co.id"
    return "https://partner.api.bri.co.id"


def _get_timestamp() -> str:
    """ISO 8601 timestamp: 2026-05-14T12:00:00.000+07:00"""
    from datetime import timedelta
    now = datetime.now(timezone.utc) + timedelta(hours=7)
    return now.strftime("%Y-%m-%dT%H:%M:%S.000+07:00")


# ══════════════════════════════════════════════════════════════════════════════
# SIGNATURES
# ══════════════════════════════════════════════════════════════════════════════

def generate_asymmetric_signature(client_id: str, private_key_pem: str, timestamp: str) -> str:
    """RSA-SHA256 signature untuk request access token.
    StringToSign = client_id + "|" + timestamp
    """
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
    """HMAC-SHA512 signature untuk API request.
    StringToSign = HTTPMethod + ":" + URLPath + ":" + AccessToken
                 + ":" + Lowercase(HexEncode(SHA-256(minify(body))))
                 + ":" + Timestamp
    """
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
    """Verify signature dari BRI callback."""
    expected = generate_symmetric_signature(
        http_method, url_path, access_token, request_body, timestamp, client_secret
    )
    return hmac.compare_digest(expected, received_signature)


# ══════════════════════════════════════════════════════════════════════════════
# API CALLS
# ══════════════════════════════════════════════════════════════════════════════

_access_token_cache = {"token": "", "expires_at": ""}
_token_lock = None  # Inisialisasi lazy di dalam coroutine (event loop belum ada saat import)

def _get_token_lock():
    """Lazy-init asyncio.Lock agar aman diimport sebelum event loop berjalan."""
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
    """OAuth 2.0 B2B Client Credentials — POST /snap/v1.0/access-token/b2b

    Thread-safe via asyncio.Lock: hanya satu coroutine yang bisa refresh token,
    yang lain menunggu dan memakai token yang sudah di-cache.
    """
    if not config:
        config = _get_bri_config()

    # Fast path: cek cache tanpa lock
    if (_access_token_cache["token"] and
            _access_token_cache["expires_at"] > datetime.now(timezone.utc).isoformat()):
        return _access_token_cache["token"]

    # Slow path: acquire lock, refresh token
    async with _get_token_lock():
        # Re-check setelah acquire (another coroutine mungkin sudah refresh)
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
            raise Exception(f"BRI OAuth failed: {data}")

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
    """Generate QRIS MPM Dynamic — POST /snap/v1.0/qr/qr-mpm-generate
    
    Args:
        partner_ref_no: Reference unik (e.g. "CLT001-INV20260501-1715000")
        amount: Jumlah dalam Rupiah
        validity_seconds: Masa berlaku QR (default 10 menit)
    
    Returns:
        dict: {"qr_content": "...", "qr_url": "...", "ref_no": "...", "raw": {...}}
    """
    if not config:
        config = _get_bri_config()

    if not config["enabled"]:
        raise Exception("BRI QRIS belum diaktifkan. Aktifkan di Pengaturan.")

    access_token = await get_access_token(config)
    base_url = _get_base_url(config)
    timestamp = _get_timestamp()
    url_path = "/snap/v1.0/qr/qr-mpm-generate"
    external_id = str(uuid.uuid4())

    body = {
        "partnerReferenceNo": partner_ref_no,
        "amount": {"value": f"{amount}.00", "currency": "IDR"},
        # Gunakan merchant_id dari DB (bukan partner_id — keduanya bisa berbeda)
        "merchantId": config["merchant_id"],
        # Gunakan terminal_id dari DB (bukan hard-coded TERM01)
        "terminalId": config["terminal_id"],
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
        "X-PARTNER-ID": config["partner_id"],
        "X-EXTERNAL-ID": external_id,
        "CHANNEL-ID": "QRI",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}{url_path}", headers=headers, content=body_str)
        data = resp.json()

    response_code = data.get("responseCode", "")
    if response_code != "2004700" and resp.status_code not in (200, 201):
        raise Exception(f"BRI QRIS generate failed: {data}")

    return {
        "qr_content": data.get("qrContent", ""),
        "qr_url": data.get("qrUrl", ""),
        "ref_no": data.get("referenceNo", ""),
        "partner_ref_no": partner_ref_no,
        "raw": data
    }


async def query_qris_status(partner_ref_no: str, config: dict = None) -> dict:
    """Query status QRIS — POST /snap/v1.0/qr/qr-mpm-query"""
    if not config:
        config = _get_bri_config()

    access_token = await get_access_token(config)
    base_url = _get_base_url(config)
    timestamp = _get_timestamp()
    url_path = "/snap/v1.0/qr/qr-mpm-query"

    body = {
        "originalPartnerReferenceNo": partner_ref_no,
        "serviceCode": "47",
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
        "X-PARTNER-ID": config["partner_id"],
        "X-EXTERNAL-ID": str(uuid.uuid4()),
        "CHANNEL-ID": "QRI",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}{url_path}", headers=headers, content=body_str)
        return resp.json()


async def test_connection() -> dict:
    """Test BRI API connection — validasi semua field kritis, lalu coba get access token."""
    try:
        config = _get_bri_config()
        # Validasi field wajib sebelum mencoba koneksi
        if not config["client_id"] or not config["client_secret"]:
            return {"success": False, "message": "❌ Client ID atau Client Secret BRI belum diisi."}
        if not config["private_key_pem"]:
            return {"success": False, "message": "❌ Private Key PEM BRI belum diisi."}
        if not config["partner_id"]:
            return {"success": False, "message": "❌ Partner ID BRI belum diisi. Field ini wajib untuk header X-PARTNER-ID pada setiap transaksi QRIS."}
        if not config["merchant_id"]:
            return {"success": False, "message": "❌ Merchant ID BRI belum diisi. Field ini wajib sebagai merchantId pada body generate QRIS."}
        # Coba dapatkan access token
        token = await get_access_token(config)
        return {"success": True, "message": f"✅ Koneksi BRI SNAP berhasil! Token: {token[:20]}... (Partner ID: {config['partner_id']}, Merchant ID: {config['merchant_id']})"}
    except Exception as e:
        return {"success": False, "message": f"❌ Gagal koneksi ke BRI SNAP: {str(e)}"}
