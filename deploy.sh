#!/bin/bash
# ============================================================
# GROM_OCR — Script de Deploy Automatizado para Linux (ARM/x86)
# Oracle Cloud Free Tier / VPS Ubuntu 22.04+
# ============================================================
# Uso: sudo bash deploy.sh
# ============================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

INSTALL_DIR="/var/www/grom-ocr"
DOMAIN=""
ENABLE_SSL="n"

echo -e "${CYAN}"
echo "=================================================="
echo "   GROM_OCR — Deploy Automatizado (Linux)"
echo "=================================================="
echo -e "${NC}"

# --- Verificar root ---
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Execute como root: sudo bash deploy.sh${NC}"
    exit 1
fi

# --- Perguntas interativas ---
read -p "Domínio ou IP público do servidor (ex: ocr.seudominio.com.br): " DOMAIN
if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Domínio/IP é obrigatório.${NC}"
    exit 1
fi

read -p "Senha para o banco MySQL (grom_ocr): " DB_PASS
if [ -z "$DB_PASS" ]; then
    DB_PASS="grom_ocr_$(openssl rand -hex 6)"
    echo -e "${YELLOW}Senha gerada automaticamente: ${DB_PASS}${NC}"
fi

read -p "Deseja configurar HTTPS com Let's Encrypt? (s/n) [n]: " ENABLE_SSL
ENABLE_SSL=${ENABLE_SSL:-n}

echo ""
echo -e "${GREEN}[1/8] Atualizando sistema...${NC}"
apt update && apt upgrade -y

echo -e "${GREEN}[2/8] Instalando dependências do sistema...${NC}"
apt install -y software-properties-common curl git unzip

# PHP 8.3
add-apt-repository ppa:ondrej/php -y 2>/dev/null || true
apt update
apt install -y php8.3 php8.3-fpm php8.3-cli php8.3-mysql php8.3-sqlite3 \
    php8.3-mbstring php8.3-xml php8.3-curl php8.3-gd php8.3-zip

# Nginx
apt install -y nginx

# Python 3
apt install -y python3 python3-venv python3-pip

# MariaDB
apt install -y mariadb-server mariadb-client

# Tesseract OCR
apt install -y tesseract-ocr tesseract-ocr-por

# OpenCV deps
apt install -y libgl1-mesa-glx libglib2.0-0 || true

# Certbot (SSL)
if [ "$ENABLE_SSL" = "s" ] || [ "$ENABLE_SSL" = "S" ]; then
    apt install -y certbot python3-certbot-nginx
fi

echo -e "${GREEN}[3/8] Configurando banco de dados MariaDB...${NC}"
mysql -u root -e "CREATE DATABASE IF NOT EXISTS grom_ocr CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null || true
mysql -u root -e "CREATE USER IF NOT EXISTS 'grom'@'localhost' IDENTIFIED BY '${DB_PASS}';" 2>/dev/null || true
mysql -u root -e "GRANT ALL PRIVILEGES ON grom_ocr.* TO 'grom'@'localhost';" 2>/dev/null || true
mysql -u root -e "FLUSH PRIVILEGES;" 2>/dev/null || true

echo -e "${GREEN}[4/8] Preparando diretório do projeto...${NC}"
mkdir -p "$INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Projeto já existe, atualizando..."
    cd "$INSTALL_DIR" && git pull || true
else
    echo -e "${YELLOW}Copie os arquivos do projeto para: ${INSTALL_DIR}${NC}"
    echo "Use: scp -r C:\\Grom_OCR\\* usuario@servidor:${INSTALL_DIR}/"
fi

echo -e "${GREEN}[5/8] Configurando ambiente Python...${NC}"
cd "$INSTALL_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip
pip install flask opencv-python-headless numpy pytesseract werkzeug requests fpdf Pillow waitress
pip install rapidocr-onnxruntime || echo -e "${YELLOW}RapidOCR falhou (opcional)${NC}"

deactivate

echo -e "${GREEN}[6/8] Configurando variáveis de ambiente (.env)...${NC}"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    if [ -f "$INSTALL_DIR/.env.server" ]; then
        cp "$INSTALL_DIR/.env.server" "$INSTALL_DIR/.env"
    fi
fi

# Atualizar senha do banco no .env
if [ -f "$INSTALL_DIR/.env" ]; then
    sed -i "s/TROCAR_POR_SENHA_FORTE/${DB_PASS}/" "$INSTALL_DIR/.env"
fi

echo -e "${GREEN}[7/8] Configurando Nginx...${NC}"
cat > /etc/nginx/sites-available/grom-ocr << NGINX_CONF
server {
    listen 80;
    server_name ${DOMAIN};

    root ${INSTALL_DIR}/public;
    index index.php;

    client_max_body_size 80M;

    # Segurança: bloquear acesso a arquivos sensíveis
    location ~ /\\.env { deny all; }
    location ~ /\\.git { deny all; }
    location ~ /\\.ht  { deny all; }

    location / {
        try_files \$uri \$uri/ /index.php?\$query_string;
    }

    location ~ \\.php\$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php8.3-fpm.sock;

        # Variáveis de ambiente Grom_OCR
        fastcgi_param GROM_OCR_MODE server;
        fastcgi_param GROM_OCR_PYTHON_API_URL http://127.0.0.1:5000;
        fastcgi_param GROM_OCR_DB_DRIVER mysql;
        fastcgi_param GROM_OCR_DB_HOST localhost;
        fastcgi_param GROM_OCR_DB_NAME grom_ocr;
        fastcgi_param GROM_OCR_DB_USER grom;
        fastcgi_param GROM_OCR_DB_PASS ${DB_PASS};
    }

    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)\$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
NGINX_CONF

ln -sf /etc/nginx/sites-available/grom-ocr /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo -e "${GREEN}[8/8] Configurando serviço Python API (systemd)...${NC}"
cat > /etc/systemd/system/grom-ocr-api.service << SERVICE_CONF
[Unit]
Description=Grom_OCR Python API (Motor de IA Pericial)
After=network.target mariadb.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python -m waitress --host=127.0.0.1 --port=5000 --call python.ocr_agent:create_app 2>/dev/null || ${INSTALL_DIR}/.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from python.ocr_agent import app; from waitress import serve; serve(app, host='127.0.0.1', port=5000)"

# Variáveis de ambiente (modo servidor leve)
Environment="GROM_OCR_MODE=server"
Environment="GROM_OCR_ENABLE_EASYOCR=0"
Environment="GROM_OCR_ENABLE_RAPIDOCR=1"
Environment="GROM_OCR_ENABLE_PADDLEOCR=0"
Environment="GROM_OCR_ENABLE_YOLO_DETECTOR=0"
Environment="GROM_OCR_ENABLE_TROCR=0"
Environment="GROM_OCR_ENABLE_DOCTR=0"
Environment="GROM_OCR_ENABLE_PDF_INPUT=1"
Environment="GROM_OCR_SCENE_PREPROCESS_ENABLE=1"
Environment="GROM_OCR_FORENSIC_TRAITS_ENABLE=1"
Environment="GROM_OCR_VISUAL_PROFILE_ENABLE=1"

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_CONF

systemctl daemon-reload
systemctl enable grom-ocr-api

# Importar schema do banco
if [ -f "$INSTALL_DIR/config/migrations.sql" ]; then
    mysql -u grom -p"${DB_PASS}" grom_ocr < "$INSTALL_DIR/config/migrations.sql" 2>/dev/null || true
fi

# Permissões
chown -R www-data:www-data "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod -R 775 "$INSTALL_DIR/data" 2>/dev/null || true
chmod -R 775 "$INSTALL_DIR/downloads" 2>/dev/null || true
mkdir -p "$INSTALL_DIR/data/uploads" && chown www-data:www-data "$INSTALL_DIR/data/uploads"

# Iniciar API
systemctl start grom-ocr-api

# SSL
if [ "$ENABLE_SSL" = "s" ] || [ "$ENABLE_SSL" = "S" ]; then
    echo -e "${GREEN}Configurando HTTPS (Let's Encrypt)...${NC}"
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || \
        echo -e "${YELLOW}SSL falhou. Configure manualmente: sudo certbot --nginx -d ${DOMAIN}${NC}"
fi

# Anti-idle (evitar reclamação de VM ociosa da Oracle)
CRON_JOB='*/5 * * * * /usr/bin/python3 -c "import time; [sum(range(10000)) for _ in range(100)]" > /dev/null 2>&1'
(crontab -l 2>/dev/null | grep -v "sum(range" ; echo "$CRON_JOB") | crontab -

echo ""
echo -e "${CYAN}=================================================="
echo "   DEPLOY CONCLUÍDO!"
echo "=================================================="
echo -e "${NC}"
echo -e "  🌐 Acesse: ${GREEN}http://${DOMAIN}${NC}"
echo -e "  🔑 Login:  ${GREEN}admin / admin${NC}"
echo -e "  📦 DB:     grom (senha: ${DB_PASS})"
echo ""
echo -e "${YELLOW}IMPORTANTE: Troque a senha padrão!${NC}"
echo -e "  php -r \"echo password_hash('NOVA_SENHA', PASSWORD_DEFAULT);\""
echo -e "  Coloque o resultado em GROM_OCR_ADMIN_PASS_HASH no Nginx conf."
echo ""
echo -e "  Verificar status: ${GREEN}sudo systemctl status grom-ocr-api nginx php8.3-fpm mariadb${NC}"
echo ""
