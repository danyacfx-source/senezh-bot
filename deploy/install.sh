#!/usr/bin/env bash
set -euo pipefail

# Скрипт установки бота СЕНЕЖ + панели на Ubuntu Server (Oracle/любой VPS).
# Запускать: sudo bash install.sh
# Перед запуском: /opt/senezh-bot уже должен лежать со всеми файлами проекта,
# в /opt/senezh-bot/.env должен быть заполнен DISCORD_TOKEN (+ PANEL_PASSWORD и PANEL_PUBLIC_URL).

APP=/opt/senezh-bot
SERVICE=senezh-bot.service

echo "==> System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip curl

echo "==> Caddy (reverse proxy + TLS)"
if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  apt-get update -y
  apt-get install -y caddy
fi

echo "==> Create user senezh"
id -u senezh >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin --home-dir /opt/senezh-bot senezh

echo "==> Check app dir"
if [ ! -f "$APP/bot.py" ]; then
  echo "ОШИБКА: $APP/bot.py не найден. Скопируй файлы проекта в $APP и запусти заново."
  exit 1
fi

echo "==> Venv + deps"
chown -R senezh:senezh "$APP"
sudo -u senezh python3 -m venv "$APP/venv"
sudo -u senezh "$APP/venv/bin/pip" install --upgrade pip
sudo -u senezh "$APP/venv/bin/pip" install -r "$APP/requirements.txt"

echo "==> systemd unit"
cp "$APP/deploy/$SERVICE" /etc/systemd/system/$SERVICE
systemctl daemon-reload
systemctl enable $SERVICE

echo "==> Caddyfile"
if [ -f "$APP/deploy/Caddyfile" ]; then
  cp "$APP/deploy/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
else
  echo "Caddyfile нет — Caddy не настроен (панель будет доступна только по IP:17890)."
fi

echo "==> Запуск"
systemctl restart $SERVICE

echo "==> Готово. Статус:"
systemctl status $SERVICE --no-pager || true
echo "Логи: journalctl -u $SERVICE -f"