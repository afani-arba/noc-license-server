#!/usr/bin/env python3
"""
Script untuk generate QRIS BRI Sandbox dan tampilkan qrContent
Jalankan di dalam container: docker exec noc-license-backend python3 /tmp/gen_qris.py
"""
import asyncio, sys, uuid, time

# ─── ISIAN CREDENTIALS BRI SANDBOX ────────────────────────────────────────────
BRI_CLIENT_ID     = '7dsh9ZtvCUuCZ4D93zAspt8LnGXFK4GT'
BRI_CLIENT_SECRET = 'jDxwXXykvdXdbxE1'
BRI_PARTNER_ID    = '457143'
BRI_MERCHANT_ID   = '000001019000014'
BRI_TERMINAL_ID   = '15003751'
# ──────────────────────────────────────────────────────────────────────────────

AMOUNT = 10000  # Rp 10.000 untuk testing sandbox

async def main():
    sys.path.insert(0, '/app')
    import bri_qris
    from datetime import datetime, timedelta, timezone

    # Patch timestamp untuk menggunakan WIB (+07:00) karena BRI sering mewajibkan ini
    def patched_get_timestamp():
        now = datetime.now(timezone.utc) + timedelta(hours=7)
        return now.strftime("%Y-%m-%dT%H:%M:%S.000+07:00")
    bri_qris._get_timestamp = patched_get_timestamp


    # Baca private key yang sudah ada di container
    with open('/app/private.pem', 'r') as f:
        private_key_pem = f.read()

    config = {
        'client_id':      BRI_CLIENT_ID,
        'client_secret':  BRI_CLIENT_SECRET,
        'partner_id':     BRI_PARTNER_ID,
        'merchant_id':    BRI_MERCHANT_ID,
        'terminal_id':    BRI_TERMINAL_ID,
        'private_key_pem': private_key_pem,
        'enabled':        True,
        'sandbox':        True,
        'merchant_name':  'PT. Arsya',
        'merchant_city':  'Jakarta',
    }

    partner_ref = str(int(time.time() * 1000))

    print(f'\n{"="*60}')
    print(f'BRI QRIS SANDBOX GENERATOR')
    print(f'{"="*60}')
    print(f'Partner Ref : {partner_ref}')
    print(f'Amount      : Rp {AMOUNT:,}')
    print(f'Mode        : SANDBOX')
    print(f'{"="*60}\n')

    try:
        result = await bri_qris.generate_qris(
            partner_ref_no=partner_ref,
            amount=AMOUNT,
            validity_seconds=3600,
            config=config
        )
        print('STATUS  : SUCCESS!')
        print(f'\nqrContent  :\n{result["qr_content"]}\n')
        print(f'referenceNo: {result["ref_no"]}')
        print(f'qrUrl      : {result.get("qr_url", "-")}')
        print(f'\n{"="*60}')
        print('→ COPY qrContent di atas dan kirim ke grup BRI x PT. Arsya')
        print(f'{"="*60}\n')
    except Exception as e:
        print(f'ERROR: {e}')
        import traceback
        traceback.print_exc()

asyncio.run(main())
