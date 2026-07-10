"""
bri_payout.py — BRI Corporate API Disbursement / Interbank Fund Transfer
=========================================================================
Mendukung transfer ke rekening:
  - Sesama BRI  : menggunakan BRI In-House Transfer
  - Non-BRI     : menggunakan BI-FAST atau Realtime Online

Dokumentasi BRI Developer: https://developers.bri.co.id/id/product/transfer-ke-bank-lain

Auth Flow (SNAP BRI Standard):
  1. Dapatkan Access Token B2B via POST /snap/v1.0/access-token/b2b
  2. Buat signature HMAC-SHA512 dari body + timestamp + access token
  3. Panggil endpoint transfer dengan header Authorization dan signature
"""

import hashlib
import hmac
import base64
import json
import time
import uuid
import os
import httpx
import pymongo
from datetime import datetime, timezone
from field_crypto import decrypt_field
from cache import cache_get, cache_set

# ── DB untuk membaca config ────────────────────────────────────────────────────
mongo_uri  = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017/"
db_name    = os.environ.get("MONGO_DB_NAME") or os.environ.get("DB_NAME", "noc_license_server")
_client    = pymongo.MongoClient(mongo_uri)
_db        = _client[db_name]
_c_settings = _db["system_settings"]

# ── Base URL ───────────────────────────────────────────────────────────────────
BRI_PROD_URL    = "https://partner.api.bri.co.id"
BRI_SANDBOX_URL = "https://sandbox.partner.api.bri.co.id"

# Kode bank untuk BI-FAST (sumber: BI)
BANK_CODES: dict[str, str] = {
    "BRI": "002",
    "MANDIRI": "008",
    "BNI": "009",
    "BCA": "014",
    "PERMATA": "013",
    "CIMB NIAGA": "022",
    "DANAMON": "011",
    "PANIN": "019",
    "OCBC": "028",
    "BTN": "200",
    "MAYBANK": "016",
    "BSI": "451",
    "SEABANK": "076",
    "JAGO": "542",
    "NOBU": "503",
    "BNC": "069",
}


def _get_payout_config() -> dict:
    """Ambil konfigurasi BRIAPI Payout dari database (cache 60 detik)."""
    cached = cache_get("bri_payout_config")
    if cached:
        return cached

    doc = _c_settings.find_one({"id": "sys_prefs"}) or {}
    result = {
        "enabled":         doc.get("bri_payout_enabled", False),
        "sandbox":         doc.get("bri_payout_sandbox", True),
        "consumer_key":    doc.get("bri_payout_consumer_key", ""),
        # Dekripsi consumer_secret — field ini masuk dalam _SENSITIVE_FIELDS di settings.py
        # sehingga dienkripsi AES-256-GCM saat disimpan via Admin UI.
        "consumer_secret": decrypt_field(doc.get("bri_payout_consumer_secret", "")),
        "client_id":       doc.get("bri_payout_client_id", ""),
        # Dekripsi private key saat dibaca (AES-256-GCM)
        "private_key_pem": decrypt_field(doc.get("bri_payout_private_key_pem", "")),
    }
    cache_set("bri_payout_config", result, ttl=60)
    return result


def _base_url(sandbox: bool) -> str:
    return BRI_SANDBOX_URL if sandbox else BRI_PROD_URL


def _generate_timestamp() -> str:
    """ISO 8601 timestamp dengan timezone offset (SNAP standard)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _generate_external_id() -> str:
    """Unique external ID per transaksi."""
    return str(uuid.uuid4()).replace("-", "")[:20]


def _sign_access_token(consumer_key: str, private_key_pem: str, timestamp: str) -> str:
    """
    Generate Asymmetric Signature untuk mendapatkan token BRI.
    BRI menggunakan SHA256withRSA / EdDSA untuk Access Token.
    String to sign: {clientId}|{timestamp}
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        string_to_sign = f"{consumer_key}|{timestamp}"
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None
        )
        signature = private_key.sign(
            string_to_sign.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")
    except ImportError:
        # Fallback HMAC jika cryptography tidak terinstall
        sig = hmac.new(private_key_pem.encode(), f"{consumer_key}|{timestamp}".encode(), hashlib.sha256).digest()
        return base64.b64encode(sig).decode("utf-8")
    except Exception as e:
        print(f"[BRIPayout] Error signing token: {e}")
        return ""


def _sign_request(access_token: str, http_method: str, endpoint_path: str,
                  request_body: dict, timestamp: str, consumer_secret: str) -> str:
    """
    Generate HMAC-SHA512 Signature untuk request API BRI.
    String to sign: {method}:{path}:{access_token}:{body_hash}:{timestamp}
    """
    body_json = json.dumps(request_body, separators=(",", ":"))
    body_hash = hashlib.sha256(body_json.encode("utf-8")).hexdigest().lower()
    string_to_sign = f"{http_method.upper()}:{endpoint_path}:{access_token}:{body_hash}:{timestamp}"
    signature = hmac.new(
        consumer_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha512
    ).digest()
    return base64.b64encode(signature).decode("utf-8")


async def _get_b2b_token(config: dict) -> str | None:
    """
    Dapatkan B2B Access Token dari BRI SNAP.
    Di-cache 14 menit (token BRI valid 15 menit).
    Return token string, atau None jika gagal.
    """
    cache_key = f"bri_token_{config['consumer_key'][:8]}"
    cached_token = cache_get(cache_key)
    if cached_token:
        return cached_token

    timestamp = _generate_timestamp()
    signature = _sign_access_token(
        config["consumer_key"],
        config["private_key_pem"],
        timestamp
    )
    if not signature:
        return None

    url = f"{_base_url(config['sandbox'])}/snap/v1.0/access-token/b2b"
    headers = {
        "Content-Type": "application/json",
        "X-CLIENT-KEY": config["consumer_key"],
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
    }
    body = {"grantType": "client_credentials"}

    try:
        async with httpx.AsyncClient(timeout=30) as hc:
            resp = await hc.post(url, headers=headers, json=body)
            data = resp.json()
            if resp.status_code == 200 and data.get("accessToken"):
                token = data["accessToken"]
                cache_set(cache_key, token, ttl=840)  # Cache 14 menit
                return token
            else:
                print(f"[BRIPayout] Token error: {resp.status_code} — {data}")
                return None
    except Exception as e:
        print(f"[BRIPayout] Token request exception: {e}")
        return None


def _resolve_bank_code(bank_name: str) -> str:
    """Konversi nama bank ke kode bank BI."""
    key = bank_name.upper().strip()
    for bname, bcode in BANK_CODES.items():
        if bname in key:
            return bcode
    return ""


async def execute_bri_transfer(
    bank_name: str,
    account_number: str,
    account_holder: str,
    amount: int,
    notes: str = "",
    wd_id: str = "",
) -> dict:
    """
    Eksekusi transfer bank via BRI Corporate API.

    Returns dict:
        {
          "success": True/False,
          "reference_no": str,
          "message": str,
          "raw": dict  # raw BRI response
        }
    """
    config = _get_payout_config()

    # Guard: Konfigurasi belum diisi
    if not config["enabled"]:
        return {"success": False, "message": "BRI Payout belum diaktifkan di Settings.", "raw": {}}
    if not config["consumer_key"] or not config["consumer_secret"]:
        return {"success": False, "message": "Consumer Key/Secret BRI belum dikonfigurasi.", "raw": {}}

    # Guard: Minimal nominal
    if amount < 10000:
        return {"success": False, "message": f"Jumlah transfer terlalu kecil: Rp {amount:,}", "raw": {}}

    # Step 1: Dapatkan Access Token
    access_token = await _get_b2b_token(config)
    if not access_token:
        return {"success": False, "message": "Gagal mendapatkan Access Token dari BRI.", "raw": {}}

    # Step 2: Siapkan payload transfer
    is_bri = "bri" in bank_name.lower()
    bank_code = "002" if is_bri else _resolve_bank_code(bank_name)
    external_id = _generate_external_id()
    timestamp = _generate_timestamp()

    if is_bri:
        # BRI In-House / BI-FAST Internal
        endpoint = "/snap/v1.0/transfer-intrabank"
        endpoint_snap = "/transfer-intrabank"
        body = {
            "partnerReferenceNo": wd_id or external_id,
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "IDR"
            },
            "beneficiaryAccountName": account_holder,
            "beneficiaryAccountNo": account_number,
            "currency": "IDR",
            "remark": notes or f"Payout NOC #{wd_id or external_id}"
        }
    else:
        # Interbank via BI-FAST / Realtime Online
        endpoint = "/snap/v1.0/transfer-interbank"
        endpoint_snap = "/transfer-interbank"
        body = {
            "partnerReferenceNo": wd_id or external_id,
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "IDR"
            },
            "beneficiaryBankCode": bank_code,
            "beneficiaryBankName": bank_name,
            "beneficiaryAccountName": account_holder,
            "beneficiaryAccountNo": account_number,
            "currency": "IDR",
            "remark": notes or f"Payout NOC #{wd_id or external_id}",
            "transactionDate": timestamp,
        }

    # Step 3: Sign request
    partner_id = config["client_id"] or config["consumer_key"]
    signature = _sign_request(
        access_token, "POST", endpoint_snap, body, timestamp, config["consumer_secret"]
    )

    url = f"{_base_url(config['sandbox'])}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
        "X-PARTNER-ID": partner_id,
        "X-EXTERNAL-ID": external_id,
        "CHANNEL-ID": "95231",
    }

    # Step 4: Eksekusi Transfer
    try:
        async with httpx.AsyncClient(timeout=30) as hc:
            resp = await hc.post(url, headers=headers, json=body)
            data = resp.json()

        # BRI: responseCode "2001600" = Sukses
        resp_code = data.get("responseCode", "")
        if resp.status_code in (200, 201) and resp_code.startswith("200"):
            ref_no = data.get("referenceNo", external_id)
            return {
                "success": True,
                "reference_no": ref_no,
                "message": f"Transfer berhasil. Ref: {ref_no}",
                "raw": data
            }
        else:
            err_msg = data.get("responseMessage", "Unknown error dari BRI")
            print(f"[BRIPayout] Transfer gagal: {resp_code} — {err_msg}")
            return {
                "success": False,
                "reference_no": "",
                "message": f"BRI Error {resp_code}: {err_msg}",
                "raw": data
            }
    except Exception as e:
        print(f"[BRIPayout] Transfer exception: {e}")
        return {
            "success": False,
            "reference_no": "",
            "message": f"Exception saat transfer: {str(e)}",
            "raw": {}
        }


def is_payout_configured() -> bool:
    """Helper: Cek apakah BRIAPI Payout sudah dikonfigurasi dan aktif.
    Membutuhkan: enabled=True, consumer_key, consumer_secret, DAN private_key_pem.
    Tanpa private_key_pem, Asymmetric Signature tidak bisa dibuat → execute_bri_transfer() pasti gagal.
    """
    config = _get_payout_config()
    return (
        config["enabled"]
        and bool(config["consumer_key"])
        and bool(config["consumer_secret"])
        and bool(config["private_key_pem"])   # Tambahan: wajib ada untuk buat token
    )


async def test_connection() -> dict:
    """Test connection by trying to get a B2B token."""
    config = _get_payout_config()
    token = await _get_b2b_token(config)
    if token:
        return {"success": True, "message": "Koneksi BRI Payout API Berhasil!"}
    else:
        return {"success": False, "message": "Gagal mendapatkan B2B Access Token."}
