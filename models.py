"""
Models dan helper functions untuk license management.
"""
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional


def generate_license_key() -> str:
    """Generate license key format: ARBA-XXXX-XXXX-XXXX-XXXX (uppercase alphanum)."""
    alphabet = string.ascii_uppercase + string.digits
    segments = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "ARBA-" + "-".join(segments)


def compute_expiry(license_type: str) -> Optional[datetime]:
    """Hitung tanggal kadaluarsa berdasarkan tipe lisensi."""
    now = datetime.now(timezone.utc)
    if license_type == "monthly":
        return now + timedelta(days=30)
    elif license_type == "yearly":
        return now + timedelta(days=365)
    elif license_type == "lifetime":
        return None  # tidak kadaluarsa
    raise ValueError(f"Unknown license_type: {license_type}")


def is_license_expired(license_doc: dict) -> bool:
    """Return True jika lisensi sudah kadaluarsa."""
    if not license_doc.get("is_active", False):
        return True
    expires_at = license_doc.get("expires_at")
    if expires_at is None:
        return False  # lifetime
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > expires_at


def format_license_response(doc: dict, include_instances: bool = True) -> dict:
    """Format document MongoDB ke response API (hapus _id internal)."""
    expires_at = doc.get("expires_at")
    doc_out = {
        "key":         doc["key"],
        "customer":    doc.get("customer", ""),
        "type":        doc.get("type", ""),
        "is_active":   doc.get("is_active", False),
        "is_expired":  is_license_expired(doc),
        "issued_at":   doc.get("issued_at", "").isoformat() if isinstance(doc.get("issued_at"), datetime) else doc.get("issued_at", ""),
        "expires_at":  expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at,
        "notes":       doc.get("notes", ""),
    }
    if include_instances:
        instances = doc.get("instances", [])
        # Mark online jika last_seen < 10 menit
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        for inst in instances:
            ls = inst.get("last_seen")
            if isinstance(ls, str):
                ls = datetime.fromisoformat(ls)
            if ls and ls.tzinfo is None:
                ls = ls.replace(tzinfo=timezone.utc)
            inst["is_online"] = bool(ls and ls > cutoff)
        doc_out["instances"] = instances
        doc_out["online_count"]  = sum(1 for i in instances if i.get("is_online"))
        doc_out["total_count"]   = len(instances)
    return doc_out
