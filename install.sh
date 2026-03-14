#!/bin/bash
# ============================================================
# NOC License Server — ARBA Training
# Install Script (1 perintah)
#
# Cara pakai:
#   curl -sSL https://raw.githubusercontent.com/afani-arba/noc-license-server/main/install.sh | sudo bash
# ============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
header(){ echo -e "\n${BOLD}${CYAN}══ $1 ══${NC}\n"; }

INSTALL_DIR="/opt/noc-license-server"
SERVICE_NAME="noc-license"
PORT="5001"
REPO_URL="https://github.com/afani-arba/noc-license-server.git"

header "NOC License Server — ARBA Training"
echo -e "${BOLD}Install dir : ${NC}$INSTALL_DIR"
echo -e "${BOLD}Port        : ${NC}$PORT"
echo ""

# ── 1. Cek root ──────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Jalankan sebagai root: sudo bash install.sh"

# ── 2. Update & install sistem deps ─────────────────────────────────────────
header "1. Install System Dependencies"
apt-get update -qq
apt-get install -y -qq git python3 python3-pip python3-venv curl
ok "System dependencies installed"

# ── 3. Install MongoDB (jika belum ada) ─────────────────────────────────────
header "2. Setup MongoDB"
if ! command -v mongod &>/dev/null; then
    info "Installing MongoDB..."
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" > /etc/apt/sources.list.d/mongodb-org-7.0.list
    apt-get update -qq
    apt-get install -y -qq mongodb-org
    ok "MongoDB installed"
fi
systemctl enable mongod --quiet
systemctl start mongod
sleep 2
ok "MongoDB running"

# ── 4. Clone / Update repo ───────────────────────────────────────────────────
header "3. Download License Server"
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --quiet
else
    info "Cloning repository..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi
ok "Code updated"

# ── 5. Python virtualenv & dependencies ─────────────────────────────────────
header "4. Install Python Dependencies"
cd "$INSTALL_DIR"
python3 -m venv .venv --quiet
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
ok "Python dependencies installed"

# ── 6. Setup .env ────────────────────────────────────────────────────────────
header "5. Setup Environment"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"

    # Generate random admin secret
    ADMIN_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/ganti-dengan-secret-panjang-anda/$ADMIN_SECRET/" "$INSTALL_DIR/.env"

    ok ".env dibuat dengan admin secret baru"
    warn "CATAT admin secret berikut (tidak bisa dipulihkan):"
    echo ""
    echo -e "  ${BOLD}ADMIN_SECRET=${YELLOW}$ADMIN_SECRET${NC}"
    echo ""
else
    warn ".env sudah ada — dilewati (tidak diubah)"
fi

# ── 7. Systemd service ───────────────────────────────────────────────────────
header "6. Setup Systemd Service"
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=NOC License Server ARBA
After=network.target mongod.service
Requires=mongod.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
Restart=always
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Pastikan www-data bisa akses install dir
chown -R www-data:www-data "$INSTALL_DIR"

systemctl daemon-reload
systemctl enable ${SERVICE_NAME} --quiet
systemctl restart ${SERVICE_NAME}
sleep 3

if systemctl is-active --quiet ${SERVICE_NAME}; then
    ok "Service $SERVICE_NAME berjalan di port $PORT"
else
    error "Service gagal start. Cek: journalctl -u $SERVICE_NAME -n 50"
fi

# ── 8. Test API ───────────────────────────────────────────────────────────────
header "7. Test API"
sleep 2
RESP=$(curl -sf "http://localhost:$PORT/" 2>/dev/null || echo "")
if echo "$RESP" | grep -q "running"; then
    ok "API merespons dengan baik"
else
    warn "API belum merespons — tunggu beberapa detik lalu coba: curl http://localhost:$PORT/"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
header "✅ Instalasi Selesai!"
echo -e "  ${BOLD}API URL     :${NC} http://localhost:$PORT"
echo -e "  ${BOLD}Health check:${NC} curl http://localhost:$PORT/"
echo ""
echo -e "  ${BOLD}Buat license pertama:${NC}"
echo -e "  ${CYAN}curl -X POST http://localhost:$PORT/admin/issue \\
    -H 'X-Admin-Secret: <admin_secret>' \\
    -H 'Content-Type: application/json' \\
    -d '{\"customer\": \"Nama Pelanggan\", \"license_type\": \"yearly\"}' ${NC}"
echo ""
echo -e "  ${BOLD}Monitor service:${NC} journalctl -u $SERVICE_NAME -f"
echo -e "  ${BOLD}Lihat log     :${NC} systemctl status $SERVICE_NAME"
echo ""
echo -e "${YELLOW}PENTING: Setup Cloudflare Tunnel agar bisa diakses dari internet!${NC}"
echo -e "Panduan: lihat README.md bagian 'Deploy di VPS Lokal + Cloudflare Tunnel'"
