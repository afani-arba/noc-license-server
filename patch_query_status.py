#!/usr/bin/env python3
"""Patch query_qris_status di bri_qris.py agar format sesuai requirement BRI"""

with open('/app/bri_qris.py', 'r') as f:
    content = f.read()

# Fix 1: external_id di query juga harus numeric
old_query = '''async def query_qris_status(partner_ref_no: str, config: dict = None) -> dict:
    """Query status QRIS — POST /snap/v1.1/qr/qr-mpm-query"""
    if not config:
        config = _get_bri_config()

    access_token = await get_access_token(config)
    base_url = _get_base_url(config)
    timestamp = _get_timestamp()
    url_path = "/snap/v1.1/qr/qr-mpm-query"

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
        return resp.json()'''

new_query = '''async def query_qris_status(partner_ref_no: str, config: dict = None, original_reference_no: str = None) -> dict:
    """Query status QRIS — POST /snap/v1.1/qr/qr-mpm-query"""
    if not config:
        config = _get_bri_config()

    access_token = await get_access_token(config)
    base_url = _get_base_url(config)
    timestamp = _get_timestamp()
    url_path = "/snap/v1.1/qr/qr-mpm-query"

    import time as _t
    body = {
        "originalPartnerReferenceNo": partner_ref_no,
        "originalReferenceNo": original_reference_no or partner_ref_no,
        "serviceCode": "47",
        "merchantId": config.get("merchant_id", config["partner_id"]),
        "additionalInfo": {
            "terminalId": config.get("terminal_id", "TERM01")
        }
    }
    body_str = json.dumps(body, separators=(',', ':'))
    signature = generate_symmetric_signature(
        "POST", url_path, access_token, body_str, timestamp, config["client_secret"]
    )
    external_id = str(int(_t.time() * 1000))
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
        return resp.json()'''

if old_query in content:
    content = content.replace(old_query, new_query)
    print("[OK] query_qris_status berhasil dipatch!")
else:
    print("[WARN] Pattern tidak ditemukan persis, mencoba pendekatan lain...")
    # Cari bagian yang perlu diupdate
    import re
    # Fix X-EXTERNAL-ID
    content = content.replace(
        '"X-EXTERNAL-ID": str(uuid.uuid4()),\n        "CHANNEL-ID": "QRI",\n    }\n\n    async with httpx.AsyncClient(timeout=30) as client:\n        resp = await client.post(f"{base_url}{url_path}", headers=headers, content=body_str)\n        return resp.json()',
        '"X-EXTERNAL-ID": str(int(__import__("time").time() * 1000)),\n        "CHANNEL-ID": "QRI",\n    }\n\n    async with httpx.AsyncClient(timeout=30) as client:\n        resp = await client.post(f"{base_url}{url_path}", headers=headers, content=body_str)\n        return resp.json()'
    )
    print("[PARTIAL] Hanya fix X-EXTERNAL-ID")

with open('/app/bri_qris.py', 'w') as f:
    f.write(content)

# Verifikasi
print("\n=== Verifikasi query_qris_status ===")
with open('/app/bri_qris.py', 'r') as f:
    lines = f.readlines()

in_query = False
for i, line in enumerate(lines, 1):
    if 'async def query_qris_status' in line:
        in_query = True
    if in_query:
        print(f"  L{i}: {line.rstrip()}")
        if i > 0 and 'return resp.json()' in line and in_query:
            break

print("\n[DONE] Patch selesai!")
