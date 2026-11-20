#!/bin/bash
# Setup automatico di prova, lo allineero' mai ? Lo finiro' ? Bho!
#
# Abilita l'uscita immediata in caso di errori
set -e

echo "=================================================="
echo "   DX Cluster Viewer - Installazione Automatica   "
echo "=================================================="
echo ""

# Check permessi root
if [ "$EUID" -ne 0 ]; then
  echo "[!] Esegui lo script come root (sudo ./setup.sh)"
  exit 1
fi

# 1. RACCOLTA VARIABILI INTERATTIVE
read -p "Inserisci il nome del database MariaDB [dxcluster]: " DB_NAME
DB_NAME=${DB_NAME:-dxcluster}

read -p "Inserisci l'utente MariaDB [dxuser]: " DB_USER
DB_USER=${DB_USER:-dxuser}

read -sp "Inserisci la password per l'utente DB '$DB_USER': " DB_PASS
echo ""
if [ -z "$DB_PASS" ]; then
    echo "[!] La password non può essere vuota."
    exit 1
fi

read -p "Inserisci la directory di installazione [/root/dxcluster]: " INSTALL_DIR
INSTALL_DIR=${INSTALL_DIR:-/root/dxcluster}

echo ""
echo "[*] Inizio configurazione sistema..."

# 2. INSTALLAZIONE PACCHETTI APT (Punto 3)
echo "[*] Aggiornamento repository e installazione pacchetti APT..."
apt update -y
apt install -y mariadb-server mariadb-client python3 python3-venv python3-pip git

# 3. CREAZIONE/CONFIGURAZIONE MARIADB (Punto 4)
echo "[*] Configurazione Database MariaDB ($DB_NAME)..."
systemctl start mariadb
systemctl enable mariadb

mysql -u root <<EOF
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;

USE \`${DB_NAME}\`;
CREATE TABLE IF NOT EXISTS spots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    spot_time DATETIME NOT NULL,
    frequency VARCHAR(20) NOT NULL,
    dx_call VARCHAR(20) NOT NULL,
    spotter VARCHAR(20) NOT NULL,
    comment VARCHAR(255) DEFAULT '',
    band VARCHAR(10) DEFAULT '',
    mode VARCHAR(10) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dx_call (dx_call),
    INDEX idx_spot_time (spot_time),
    INDEX idx_band_mode (band, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
EOF

# 4. AMBIENTE PYTHON VENV & REQUIREMENTS (Punto 2)
echo "[*] Configurazione ambiente virtuale Python e dipendenze..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Installa il requirements.txt se presente
if [ -f "requirements.txt" ]; then
    ./venv/bin/pip install -r requirements.txt
else
    # Fallback se il file manca
    ./venv/bin/pip install mysql-connector-python
fi

# 5. CREAZIONE ED ATTIVAZIONE DEI SERVIZI SYSTEMD (Punto 1)
echo "[*] Generazione servizi systemd..."

# dx-collector.service
cat <<EOF > /etc/systemd/system/dx-collector.service
[Unit]
Description=DX Cluster Collector Service
After=network.target mariadb.service
Wants=mariadb.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/collector.py
Restart=always
RestartSec=5s

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# dx-api.service
cat <<EOF > /etc/systemd/system/dx-api.service
[Unit]
Description=DX Cluster REST API Server
After=network.target mariadb.service
Wants=mariadb.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/api_server.py
Restart=always
RestartSec=5s

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Ricarica e avvio
echo "[*] Abilitazione e avvio dei servizi..."
systemctl daemon-reload
systemctl enable dx-collector.service dx-api.service
systemctl restart dx-collector.service dx-api.service

echo ""
echo "=================================================="
echo "   Installazione completata con successo! :D      "
echo "=================================================="

