#!/bin/bash
# =============================================================
# Установка nginx reverse proxy для Claude API
#
# Запуск на VPS с не-российским IP:
#   wget -O setup.sh <URL> && bash setup.sh
#   или:
#   scp proxy/setup-nginx-proxy.sh root@VPS_IP:/root/ && ssh root@VPS_IP bash /root/setup-nginx-proxy.sh
#
# После установки в .env бота добавить:
#   ANTHROPIC_PROXY_URL=http://VPS_IP:8443
# =============================================================

set -euo pipefail

PORT="${1:-8443}"

echo "=== Установка nginx proxy для Claude API на порту $PORT ==="

# 1. Установка nginx
echo "[1/4] Устанавливаю nginx..."
apt-get update -qq
apt-get install -y -qq nginx > /dev/null

# 2. Конфигурация
echo "[2/4] Настраиваю конфигурацию..."
cat > /etc/nginx/sites-available/claude-proxy << 'NGINX_CONF'
server {
    listen 8443;
    server_name _;

    # Максимальный размер тела запроса (base64 для Vision)
    client_max_body_size 20m;

    # Таймауты для Claude API (Vision может думать до 120s)
    proxy_connect_timeout 30s;
    proxy_send_timeout    120s;
    proxy_read_timeout    300s;

    # Отключаем буферизацию для SSE streaming
    proxy_buffering off;

    location / {
        proxy_pass https://api.anthropic.com;
        proxy_ssl_server_name on;
        proxy_set_header Host api.anthropic.com;
        proxy_set_header Connection "";
        proxy_http_version 1.1;
        proxy_pass_request_headers on;
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
    }

    location /health {
        return 200 '{"status":"ok","proxy":"claude-api-nginx"}';
        add_header Content-Type application/json;
    }
}
NGINX_CONF

# Подставляем порт
sed -i "s/listen 8443/listen $PORT/" /etc/nginx/sites-available/claude-proxy

# Активируем конфигурацию
ln -sf /etc/nginx/sites-available/claude-proxy /etc/nginx/sites-enabled/claude-proxy
rm -f /etc/nginx/sites-enabled/default

# 3. Проверка и запуск
echo "[3/4] Проверяю конфигурацию..."
nginx -t

echo "[4/4] Перезапускаю nginx..."
systemctl restart nginx
systemctl enable nginx

# 4. Проверка
echo ""
echo "=== Готово! ==="
echo ""
MY_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "Прокси запущен: http://$MY_IP:$PORT"
echo ""
echo "Проверка:"
echo "  curl http://$MY_IP:$PORT/health"
echo ""
echo "В .env бота добавить:"
echo "  ANTHROPIC_PROXY_URL=http://$MY_IP:$PORT"
echo ""

# Быстрый тест
echo "Тестирую подключение к Claude API..."
RESULT=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "http://127.0.0.1:$PORT/v1/messages" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}' \
  2>/dev/null || echo "000")

if [ "$RESULT" = "401" ]; then
    echo "✓ Прокси работает (401 = Claude API доступен, нужен API-ключ)"
elif [ "$RESULT" = "200" ]; then
    echo "✓ Прокси работает!"
else
    echo "⚠ HTTP $RESULT — проверьте настройки"
fi
