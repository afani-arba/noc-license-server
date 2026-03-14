# NOC License Server — Panduan Instalasi

**Digunakan oleh:** Admin ARBA Training untuk mengelola lisensi NOC Sentinel v4.

---

## 🚀 Install 1 Perintah

```bash
curl -sSL https://raw.githubusercontent.com/afani-arba/noc-license-server/main/install.sh | sudo bash
```

Script ini otomatis:
- Install MongoDB
- Install Python + dependencies
- Setup systemd service (`noc-license`)
- Generate admin secret acak
- Jalankan server di port **5001**

---

## 📋 Setelah Install

### Catat Admin Secret

Admin secret ditampilkan saat install. **Simpan baik-baik!**
Jika lupa, cek file: `cat /opt/noc-license-server/.env`

### Buat License Key Baru

```bash
curl -X POST http://localhost:5001/admin/issue \
  -H "X-Admin-Secret: <admin_secret_anda>" \
  -H "Content-Type: application/json" \
  -d '{"customer": "Nama Pelanggan", "license_type": "yearly"}'
```

**Tipe lisensi:** `monthly` / `yearly` / `lifetime`

### Dashboard Instance (Online/Offline)

```bash
curl http://localhost:5001/admin/instances \
  -H "X-Admin-Secret: <admin_secret_anda>"
```

### Cabut License

```bash
curl -X POST http://localhost:5001/admin/revoke \
  -H "X-Admin-Secret: <admin_secret_anda>" \
  -H "Content-Type: application/json" \
  -d '{"license_key": "ARBA-XXXX-XXXX-XXXX-XXXX", "reason": "Alasan"}'
```

---

## 🌐 Cloudflare Tunnel (Agar Bisa Diakses Internet Tanpa IP Public)

```bash
# Install cloudflared
curl -L -o cloudflared.deb \
  https://github.com/cloudflare/cloudflare/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Login & buat tunnel
cloudflared tunnel login
cloudflared tunnel create noc-license
cloudflared tunnel route dns noc-license license.arbatraining.com

# Konfigurasi
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << EOF
tunnel: <TUNNEL-ID>
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json
ingress:
  - hostname: license.arbatraining.com
    service: http://localhost:5001
  - service: http_status:404
EOF

# Jalankan sebagai service
cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

---

## 🛠️ Kelola Service

```bash
systemctl status noc-license     # cek status
systemctl restart noc-license    # restart
journalctl -u noc-license -f     # live log
```
