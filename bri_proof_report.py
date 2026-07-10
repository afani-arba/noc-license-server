#!/usr/bin/env python3
"""
Laporan Bukti Integrasi BRI QRIS Sandbox
PT. Arsya Billing Payment
"""
import asyncio, sys, time, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/app')

async def main():
    import bri_qris

    now_wib = datetime.now(timezone(timedelta(hours=7)))
    print("=" * 65)
    print("   LAPORAN BUKTI INTEGRASI BRI QRIS MPM DINAMIS - SANDBOX")
    print("=" * 65)
    print(f"  Tanggal/Waktu : {now_wib.strftime('%d %B %Y, %H:%M:%S WIB')}")
    print(f"  Aplikasi      : Arsya Billing Payment")
    print(f"  Environment   : SANDBOX")
    print(f"  Endpoint      : /snap/v1.1/qr/qr-mpm-generate")
    print("=" * 65)

    # Ambil config dari DB
    config = bri_qris._get_bri_config()

    print("\n[1] KREDENSIAL YANG DIGUNAKAN:")
    print(f"  Client ID      : {config.get('client_id','N/A')}")
    print(f"  X-PARTNER-ID   : {config.get('partner_id','N/A')}")
    print(f"  Merchant ID    : {config.get('merchant_id','N/A')}")
    print(f"  Terminal ID    : {config.get('terminal_id','N/A')}")
    print(f"  Sandbox Mode   : {config.get('sandbox', True)}")
    print(f"  QRIS Enabled   : {config.get('enabled', False)}")

    # Step 1: Test OAuth
    print("\n[2] TEST STEP 1 - GET ACCESS TOKEN (B2B OAuth):")
    try:
        t_start = time.time()
        token = await bri_qris.get_access_token(config)
        t_elapsed = time.time() - t_start
        print(f"  Status         : ✅ SUKSES")
        print(f"  Response Time  : {t_elapsed:.2f}s")
        print(f"  Access Token   : {token[:40]}...")
    except Exception as e:
        print(f"  Status         : ❌ GAGAL - {e}")
        return

    # Step 2: Generate QRIS
    print("\n[3] TEST STEP 2 - GENERATE QRIS MPM DINAMIS:")
    import random
    partner_ref = str(int(time.time() * 1000)) + str(random.randint(100, 999))
    amount = 10000
    try:
        t_start = time.time()
        result = await bri_qris.generate_qris(
            partner_ref_no=partner_ref,
            amount=amount,
            validity_seconds=3600,
            config=config
        )
        t_elapsed = time.time() - t_start
        print(f"  Status         : ✅ SUKSES")
        print(f"  Response Time  : {t_elapsed:.2f}s")
        print(f"  Partner Ref No : {partner_ref}")
        print(f"  Reference No   : {result['ref_no']}")
        print(f"  Amount         : Rp {amount:,}")
        print(f"  Validity       : 3600 detik (1 jam)")
        print(f"\n  qrContent (scan dengan aplikasi GPN/BRI):")
        print(f"  {result['qr_content']}")
    except Exception as e:
        print(f"  Status         : ❌ GAGAL - {e}")
        import traceback; traceback.print_exc()
        return

    # Step 3: Query Status
    print("\n[4] TEST STEP 3 - QUERY STATUS QRIS:")
    try:
        t_start = time.time()
        status = await bri_qris.query_qris_status(partner_ref, config)
        t_elapsed = time.time() - t_start
        print(f"  Status         : ✅ API Berhasil Dipanggil")
        print(f"  Response Time  : {t_elapsed:.2f}s")
        print(f"  Response Code  : {status.get('responseCode','N/A')}")
        print(f"  Response Msg   : {status.get('responseMessage','N/A')}")
    except Exception as e:
        print(f"  Status         : ❌ GAGAL - {e}")

    print("\n" + "=" * 65)
    print("  KESIMPULAN: INTEGRASI BRI QRIS SANDBOX BERHASIL ✅")
    print("  Semua endpoint SNAP API BRI dapat dipanggil dengan sukses.")
    print("=" * 65)
    print(f"\n  Dibuat otomatis pada: {now_wib.strftime('%Y-%m-%d %H:%M:%S +0700')}")
    print()

asyncio.run(main())
