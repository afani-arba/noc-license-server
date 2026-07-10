#!/usr/bin/env python3
"""Query status QRIS terbaru yang aktif di Sandbox"""
import asyncio, sys, json, time, random
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/app')

async def main():
    import bri_qris

    config = bri_qris._get_bri_config()
    now_wib = datetime.now(timezone(timedelta(hours=7)))

    print("=" * 65)
    print("   QUERY PAYMENT STATUS — BRI QRIS SANDBOX")
    print("=" * 65)
    print(f"  Waktu: {now_wib.strftime('%d %B %Y %H:%M:%S WIB')}")

    # Generate QRIS baru untuk query (BRI sudah bayar QRIS sebelumnya)
    # Kita query berdasarkan partnerRef yang terakhir digunakan
    # Dari log bri_payment_monitor, ambil partner_ref yang terbaru

    # Coba query beberapa partnerRef terakhir yang mungkin
    import httpx, hashlib, hmac, base64, uuid
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    BASE_URL = "https://sandbox.partner.api.bri.co.id"

    def get_ts():
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')

    # Get token
    with open('/app/private.pem', 'r') as f:
        pk_pem = f.read()
    t = get_ts()
    pk = serialization.load_pem_private_key(pk_pem.encode(), password=None)
    sig = base64.b64encode(pk.sign(
        f"{config['client_id']}|{t}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )).decode()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BASE_URL}/snap/v1.0/access-token/b2b",
            headers={"Content-Type":"application/json","X-CLIENT-KEY":config['client_id'],"X-TIMESTAMP":t,"X-SIGNATURE":sig},
            json={"grantType":"client_credentials"})
    token = r.json().get("accessToken")
    print(f"\n[OK] Token: {token[:30]}...")

    # Query dengan invoice_number dari BRI: 19364339151936433915
    # Juga coba query semua referenceNo yang mungkin
    print("\n[QUERY] Mencari transaksi yang sudah dibayar BRI...")

    # Gunakan originalReferenceNo dari response BRI jika ada
    # BRI response: invoice_number: "19364339151936433915"
    # Coba query menggunakan originalPartnerReferenceNo

    url_path = "/snap/v1.1/qr/qr-mpm-query"
    t2 = get_ts()

    # Query dengan invoice number dari BRI
    for partner_ref, orig_ref in [
        ("19364339151936433915", "19364339151936433915"),
        ("730176282048", "730176282048"),
        ("1783667981371524", "730176282048"),
    ]:
        body = {
            "originalPartnerReferenceNo": partner_ref,
            "originalReferenceNo": orig_ref,
            "serviceCode": "47",
            "merchantId": config.get("merchant_id", "000001019000014"),
            "additionalInfo": {
                "terminalId": config.get("terminal_id", "15003751")
            }
        }
        bs  = json.dumps(body, separators=(',', ':'))
        bh  = hashlib.sha256(bs.encode()).hexdigest().lower()
        sts = f"POST:{url_path}:{token}:{bh}:{t2}"
        sym = base64.b64encode(hmac.new(config['client_secret'].encode(), sts.encode(), hashlib.sha512).digest()).decode()
        ext = str(int(time.time() * 1000) + random.randint(1,999))
        async with httpx.AsyncClient(timeout=30) as c:
            r2 = await c.post(f"{BASE_URL}{url_path}",
                headers={
                    "Content-Type":"application/json",
                    "Authorization":f"Bearer {token}",
                    "X-TIMESTAMP":t2,
                    "X-SIGNATURE":sym,
                    "X-PARTNER-ID":config['partner_id'],
                    "X-EXTERNAL-ID":ext,
                    "CHANNEL-ID":"QRI"
                }, content=bs)
        d = r2.json()
        print(f"\n  Query partnerRef={partner_ref} origRef={orig_ref}:")
        print(f"  HTTP: {r2.status_code}")
        print(f"  Response: {json.dumps(d, indent=4)}")

asyncio.run(main())
