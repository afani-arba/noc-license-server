from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import os
import pymongo
from auth import require_admin
try:
    from field_crypto import encrypt_field, decrypt_field, is_encrypted
except ImportError:
    def encrypt_field(v): return v
    def decrypt_field(v): return v
    def is_encrypted(v): return False

router = APIRouter()

mongo_uri = os.environ.get("MONGO_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017/"
db_name = os.environ.get("MONGO_DB_NAME") or os.environ.get("DB_NAME", "nocsentinel")
client = pymongo.MongoClient(mongo_uri)
db = client[db_name]
c_settings = db["system_settings"]

class SettingsUpdate(BaseModel):
    # Webhook / Payment Gateway (optional)
    payment_webhook_secret: Optional[str] = None
    # WhatsApp Gateway (Fonnte)
    wa_gateway_enabled: Optional[bool] = None
    wa_fonnte_token: Optional[str] = None
    wa_fonnte_sender: Optional[str] = None   # nomor pengirim (opsional, tergantung Fonnte plan)
    wa_fonnte_device: Optional[str] = None   # device ID Fonnte (opsional)
    wa_admin_phone: Optional[str] = None     # Nomor WA Admin untuk alert system (62xxx)
    # AI & Auto-Responder
    ai_enabled: Optional[bool] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ai_system_prompt: Optional[str] = None
    # Notification templates
    template_wa_client: Optional[str] = None        # saat klien baru didaftarkan
    template_wa_license: Optional[str] = None       # saat invoice lunas / lisensi aktif
    template_wa_dunning: Optional[str] = None       # saat lisensi hampir kadaluarsa (7 hari)
    template_email_client: Optional[str] = None     # email template
    # Company profile (stored in DB, images saved locally)
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    company_logo_url: Optional[str] = None          # path lokal /uploads/logo.png
    admin_name: Optional[str] = None
    admin_signature_url: Optional[str] = None       # path lokal /uploads/signature.png
    # BRI QRIS Config
    bri_client_id: Optional[str] = None
    bri_client_secret: Optional[str] = None
    bri_partner_id: Optional[str] = None
    bri_private_key_pem: Optional[str] = None        # Full PEM content
    bri_qris_enabled: Optional[bool] = None
    bri_qris_sandbox: Optional[bool] = None           # True=sandbox, False=production
    bri_merchant_name: Optional[str] = None
    bri_merchant_city: Optional[str] = None
    bri_merchant_id: Optional[str] = None          # Merchant ID khusus dari BRI (beda dengan Partner ID)
    bri_terminal_id: Optional[str] = None          # Terminal ID per lokasi/sistem
    # BNI QRIS Config
    bni_client_id: Optional[str] = None
    bni_client_secret: Optional[str] = None
    bni_private_key_pem: Optional[str] = None
    bni_qris_sandbox: Optional[bool] = None
    bni_qris_enabled: Optional[bool] = None
    # Primary License QRIS (bri/bni)
    primary_license_qris: Optional[str] = None
    # BRI Payout / Disbursement Config
    bri_payout_enabled: Optional[bool] = None          # True = auto transfer aktif
    bri_payout_sandbox: Optional[bool] = None          # True = sandbox mode
    bri_payout_consumer_key: Optional[str] = None
    bri_payout_consumer_secret: Optional[str] = None
    bri_payout_client_id: Optional[str] = None         # BRI Partner ID untuk payout
    bri_payout_private_key_pem: Optional[str] = None   # Private key RSA/EdDSA (PEM format)

DEFAULT_SETTINGS = {
    "id": "sys_prefs",
    "payment_webhook_secret": "",
    # WhatsApp Gateway
    "wa_gateway_enabled": False,
    "wa_fonnte_token": "",
    "wa_fonnte_sender": "",
    "wa_fonnte_device": "",
    "wa_admin_phone": "",
    # AI Config
    "ai_enabled": False,
    "gemini_api_key": "",
    "gemini_model": "gemini-1.5-flash",
    "ai_system_prompt": "Kamu adalah Customer Service. Jawab singkat dan ramah.",
    # Templates
    "template_wa_client": (
        "Halo {nama}, terima kasih telah mendaftar di sistem kami! 🎉\n\n"
        "📱 No. WhatsApp: {telepon}\n"
        "📦 Paket   : {produk}\n\n"
        "Invoice akan segera kami kirimkan. Silakan lakukan pembayaran untuk mengaktifkan lisensi Anda.\n\n"
        "Salam,\nTim NOC Sentinel"
    ),
    "template_wa_license": (
        "✅ Pembayaran Anda telah dikonfirmasi!\n\n"
        "Halo {nama}, berikut detail lisensi Anda:\n"
        "🔑 License Key : {key}\n"
        "📅 Masa Aktif  : {expired}\n\n"
        "Gunakan key ini untuk mengaktifkan NOC Sentinel. Terima kasih! 🙏"
    ),
    "template_wa_dunning": (
        "⚠️ Pengingat Perpanjangan Lisensi\n\n"
        "Halo {nama}, lisensi NOC Sentinel Anda akan kadaluarsa pada {expired}.\n"
        "💰 Total Tagihan: Rp {nominal}\n\n"
        "Segera lakukan pembayaran untuk menghindari gangguan layanan.\n"
        "Info lebih lanjut, balas pesan ini.\n\nTerima kasih 🙏"
    ),
    "template_email_client": (
        "Subjek: Selamat Datang!\n\n"
        "Halo {nama},\nSelamat bergabung bersama NOC Sentinel.\n"
        "Email terdaftar: {email}\nProduk yang dibeli: {produk}"
    ),
    # Company
    "company_name": "NOC Sentinel",
    "company_address": "Jl. Teknologi No. 1, Jakarta",
    "company_logo_url": "",
    "admin_name": "Administrator",
    "admin_signature_url": "",
    # BRI QRIS
    "bri_client_id": "",
    "bri_client_secret": "",
    "bri_partner_id": "",
    "bri_private_key_pem": "",
    "bri_qris_enabled": False,
    "bri_qris_sandbox": True,
    "bri_merchant_name": "NOC License Server",
    "bri_merchant_city": "Jakarta",
    "bri_merchant_id": "",           # Merchant ID dari BRI (wajib untuk generate QRIS)
    "bri_terminal_id": "TERM01",     # Terminal ID (default TERM01, bisa dikustomisasi)
    # BNI QRIS
    "bni_client_id": "",
    "bni_client_secret": "",
    "bni_private_key_pem": "",
    "bni_qris_sandbox": True,
    "bni_qris_enabled": False,
    # Primary License QRIS
    "primary_license_qris": "bri",
    # BRI Payout / Disbursement
    "bri_payout_enabled": False,
    "bri_payout_sandbox": True,
    "bri_payout_consumer_key": "",
    "bri_payout_consumer_secret": "",
    "bri_payout_client_id": "",
    "bri_payout_private_key_pem": "",
}

@router.get("")
def get_settings(admin: str = Depends(require_admin)):
    doc = c_settings.find_one({"id": "sys_prefs"})
    if not doc:
        doc = DEFAULT_SETTINGS.copy()
        c_settings.insert_one(doc)
    doc.pop("_id", None)
    # Ensure all new fields exist in older documents
    for key, val in DEFAULT_SETTINGS.items():
        if key not in doc:
            doc[key] = val
    return doc

@router.post("")
def update_settings(req: SettingsUpdate, admin: str = Depends(require_admin)):
    doc = c_settings.find_one({"id": "sys_prefs"})
    if not doc:
        c_settings.insert_one({"id": "sys_prefs"})

    update_data = {}
    for field, value in req.model_dump().items():
        if value is not None:
            update_data[field] = value

    # Enkripsi field sensitif sebelum disimpan ke DB
    _SENSITIVE_FIELDS = [
        "bri_payout_private_key_pem",
        "bri_payout_consumer_secret",
        "bri_private_key_pem",
        "bri_client_secret",
        "bni_private_key_pem",
        "bni_client_secret",
    ]
    for sf in _SENSITIVE_FIELDS:
        if sf in update_data and update_data[sf] and not is_encrypted(update_data[sf]):
            update_data[sf] = encrypt_field(update_data[sf])

    if update_data:
        c_settings.update_one({"id": "sys_prefs"}, {"$set": update_data})

    return {"message": "Pengaturan berhasil disimpan"}


# ── Helper access functions ────────────────────────────────────────────────────

def get_payment_secret():
    doc = c_settings.find_one({"id": "sys_prefs"})
    if doc and doc.get("payment_webhook_secret"):
        return doc["payment_webhook_secret"]
    return ""

def get_wa_config() -> dict:
    """Returns WhatsApp Gateway config dict."""
    doc = c_settings.find_one({"id": "sys_prefs"}) or {}
    return {
        "enabled": doc.get("wa_gateway_enabled", False),
        "token": doc.get("wa_fonnte_token", ""),
        "sender": doc.get("wa_fonnte_sender", ""),
        "device": doc.get("wa_fonnte_device", ""),
    }

def get_wa_template(template_key: str, **kwargs) -> str:
    """Get and render a WA template. template_key = 'template_wa_client' etc."""
    doc = c_settings.find_one({"id": "sys_prefs"}) or {}
    tmpl = doc.get(template_key, DEFAULT_SETTINGS.get(template_key, ""))
    for k, v in kwargs.items():
        tmpl = tmpl.replace("{" + k + "}", str(v))
    return tmpl
