# NOC License Server

Server lisensi terpusat untuk **NOC Sentinel v4** — ARBA Training.

## Struktur Folder

```
noc-license-server/
├── main.py          # FastAPI app + semua endpoint
├── database.py      # Koneksi MongoDB
├── models.py        # Helper: generate key, expiry, format
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Salin dan isi file .env
cp .env.example .env
nano .env

# 3. Jalankan server
uvicorn main:app --host 0.0.0.0 --port 5001 --reload
```

## Endpoints

| Method | Path | Keterangan |
|--------|------|------------|
| `GET`  | `/` | Health check |
| `POST` | `/validate` | Validasi license dari client |
| `POST` | `/heartbeat` | Update last_seen instance |
| `GET`  | `/admin/licenses` | List semua lisensi |
| `GET`  | `/admin/instances` | Dashboard semua instance |
| `POST` | `/admin/issue` | Buat license baru |
| `POST` | `/admin/revoke` | Cabut license |

## Admin API (Header: X-Admin-Secret)

```bash
# Buat license baru
curl -X POST http://localhost:5001/admin/issue \
  -H "X-Admin-Secret: secret-anda" \
  -H "Content-Type: application/json" \
  -d '{"customer": "CV Maju Jaya", "license_type": "yearly", "notes": "Pelanggan baru"}'

# List semua license
curl http://localhost:5001/admin/licenses \
  -H "X-Admin-Secret: secret-anda"

# Dashboard instances
curl http://localhost:5001/admin/instances \
  -H "X-Admin-Secret: secret-anda"

# Cabut license
curl -X POST http://localhost:5001/admin/revoke \
  -H "X-Admin-Secret: secret-anda" \
  -H "Content-Type: application/json" \
  -d '{"license_key": "ARBA-XXXX-XXXX-XXXX-XXXX", "reason": "Pembayaran gagal"}'
```

## Deploy di VPS Lokal + Cloudflare Tunnel

```bash
# 1. Install cloudflared
curl -L -o cloudflared.deb \
  https://github.com/cloudflare/cloudflare/releases/latest/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# 2. Login
cloudflared tunnel login

# 3. Buat tunnel
cloudflared tunnel create noc-license

# 4. Konfigurasi DNS (ganti dengan domain Anda)
cloudflared tunnel route dns noc-license license.arbatraining.com

# 5. Buat config tunnel (~/.cloudflared/config.yml)
cat > ~/.cloudflared/config.yml << EOF
tunnel: <TUNNEL-ID>
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json
ingress:
  - hostname: license.arbatraining.com
    service: http://localhost:5001
  - service: http_status:404
EOF

# 6. Install sebagai systemd service
cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

## Deploy sebagai systemd service (License Server)

```bash
# Buat service file
sudo nano /etc/systemd/system/noc-license.service
```

```ini
[Unit]
Description=NOC License Server ARBA
After=network.target mongod.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/noc-license-server
ExecStart=/opt/noc-license-server/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 5001
Restart=always
RestartSec=5
EnvironmentFile=/opt/noc-license-server/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable noc-license
sudo systemctl start noc-license
sudo systemctl status noc-license
```

## Format License Key

```
ARBA-XXXX-XXXX-XXXX-XXXX
     ↑ 4 karakter alphanumeric uppercase per segment
```

Contoh: `ARBA-A3FX-B9KL-7MNQ-WXYZ`

## Tipe Lisensi

| Tipe | Durasi | Keterangan |
|------|--------|------------|
| `monthly` | 30 hari | Berlangganan bulanan |
| `yearly` | 365 hari | Berlangganan tahunan |
| `lifetime` | Tidak terbatas | Sekali bayar |

## Grace Period (di Client)

Jika license server tidak bisa dihubungi, client masih bisa jalan selama **48 jam** menggunakan cache lokal. Setelah 48 jam, aplikasi akan diblokir sampai koneksi berhasil.
