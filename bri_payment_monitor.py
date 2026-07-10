#!/usr/bin/env python3
"""
Script generate QRIS + polling status pembayaran
Setelah BRI bayar di Sandbox, script ini akan deteksi pembayaran berhasil
"""
import asyncio, sys, time, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/app')

async def main():
    import bri_qris, random

    now_wib = datetime.now(timezone(timedelta(hours=7)))
    config = bri_qris._get_bri_config()

    print("=" * 65)
    print("   BRI QRIS SANDBOX — GENERATE & MONITOR PEMBAYARAN")
    print("=" * 65)
    print(f"  Waktu   : {now_wib.strftime('%d %B %Y %H:%M:%S WIB')}")
    print(f"  MID     : {config.get('merchant_id','N/A')}")
    print(f"  TID     : {config.get('terminal_id','N/A')}")
    print("=" * 65)

    # Generate QRIS
    partner_ref = str(int(time.time() * 1000)) + str(random.randint(100, 999))
    amount = 10000

    print(f"\n[1] Generating QRIS...")
    print(f"    Partner Ref No : {partner_ref}")
    print(f"    Amount         : Rp {amount:,}")

    try:
        result = await bri_qris.generate_qris(
            partner_ref_no=partner_ref,
            amount=amount,
            validity_seconds=3600,
            config=config
        )
        print(f"    Reference No   : {result['ref_no']}")
        print(f"\n{'='*65}")
        print(f"  *** KIRIM qrContent INI KE TIM BRI UNTUK DI-BAYAR ***")
        print(f"{'='*65}")
        print(f"\n  qrContent:")
        print(f"  {result['qr_content']}")
        print(f"\n{'='*65}")
        print(f"  Partner Ref No: {partner_ref}")
        print(f"  Reference No  : {result['ref_no']}")
        print(f"{'='*65}")
    except Exception as e:
        print(f"    [ERROR] {e}")
        return

    # Polling status pembayaran setiap 10 detik selama 10 menit
    print(f"\n[2] Menunggu pembayaran dari BRI... (cek setiap 10 detik, max 10 menit)")
    print(f"    Tekan Ctrl+C untuk berhenti\n")

    for i in range(60):  # 60 x 10s = 10 menit
        await asyncio.sleep(10)
        waktu = datetime.now(timezone(timedelta(hours=7))).strftime('%H:%M:%S')
        try:
            status = await bri_qris.query_qris_status(partner_ref, config)
            code = status.get('responseCode', 'N/A')
            msg  = status.get('responseMessage', 'N/A')
            
            # Parse status pembayaran
            trx_status = status.get('transactionStatus', status.get('status', ''))
            
            print(f"  [{waktu}] Check #{i+1}: Code={code} | {msg} | TrxStatus={trx_status}")
            
            # Jika sudah dibayar
            if code in ['2005100', '200'] or trx_status in ['SUCCESS', 'PAID', '00', 'settlement']:
                print(f"\n{'='*65}")
                print(f"  *** 🎉 PEMBAYARAN BERHASIL! ***")
                print(f"{'='*65}")
                print(f"  Response Code  : {code}")
                print(f"  Status         : {msg}")
                print(f"  Full Response  :")
                print(f"  {json.dumps(status, indent=4)}")
                print(f"{'='*65}")
                return

            # Jika masih pending (QRIS belum dibayar)
            if code in ['4005101', '4025100', '4005100']:
                # Masih waiting — ini normal
                pass

        except Exception as e:
            print(f"  [{waktu}] Check #{i+1}: ERROR - {e}")

    print(f"\n  Timeout 10 menit. QRIS belum dibayar.")

asyncio.run(main())
