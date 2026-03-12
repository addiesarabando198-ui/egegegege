# Альтернативная установка SSL сертификата через acme.sh

## Проблема
На вашем сервере certbot не работает из-за поврежденных зависимостей (ModuleNotFoundError: No module named 'cryptography'). Также есть проблемы с DNS/репозиториями Ubuntu.

## Решение: использовать acme.sh

acme.sh - это чистый shell-скрипт для получения SSL сертификатов от Let's Encrypt без зависимостей.

## Шаг 1: Установка acme.sh

Выполните на вашем сервере (root@ruvds-7v2lp):

```bash
# Скачать и установить acme.sh
curl https://get.acme.sh | sh

# Или если curl не работает с HTTPS, используйте:
wget -O -  https://get.acme.sh | sh

# Перезагрузить профиль bash чтобы загрузить команду
source ~/.bashrc
```

## Шаг 2: Получить SSL сертификат

Сначала убедитесь что Nginx установлен и запущен:

```bash
# Проверка Nginx
nginx -v
systemctl status nginx

# Если Nginx не установлен:
apt update && apt install nginx -y
systemctl start nginx
systemctl enable nginx
```

Теперь получите сертификат используя webroot метод:

```bash
# Создайте директорию для вебрута
mkdir -p /var/www/html

# Настройте временную конфигурацию Nginx для HTTP
cat > /etc/nginx/sites-available/temp <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai обществонапальцах.рф;

    root /var/www/html;

    location /.well-known/acme-challenge/ {
        alias /var/www/html/.well-known/acme-challenge/;
    }
}
EOF

# Активируйте конфигурацию
ln -sf /etc/nginx/sites-available/temp /etc/nginx/sites-enabled/temp
nginx -t && systemctl reload nginx

# Получите сертификат (используйте punycode версию домена)
~/.acme.sh/acme.sh --issue -d xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai -w /var/www/html
```

## Шаг 3: Установить сертификат для Nginx

```bash
# Создайте директорию для сертификатов
mkdir -p /etc/nginx/ssl

# Установите сертификаты
~/.acme.sh/acme.sh --install-cert -d xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai \
  --key-file       /etc/nginx/ssl/key.pem  \
  --fullchain-file /etc/nginx/ssl/fullchain.pem \
  --reloadcmd     "systemctl reload nginx"
```

## Шаг 4: Обновить конфигурацию Nginx для WebApp

```bash
# Удалите временную конфигурацию
rm /etc/nginx/sites-enabled/temp

# Скопируйте и обновите конфигурацию WebApp
cp /home/user/ege-superbot/nginx_webapp.conf /etc/nginx/sites-available/webapp

# Обновите пути к сертификатам в конфигурации
sed -i 's|/etc/letsencrypt/live/.*/fullchain.pem|/etc/nginx/ssl/fullchain.pem|' /etc/nginx/sites-available/webapp
sed -i 's|/etc/letsencrypt/live/.*/privkey.pem|/etc/nginx/ssl/key.pem|' /etc/nginx/sites-available/webapp

# Активируйте конфигурацию
ln -sf /etc/nginx/sites-available/webapp /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## Шаг 5: Скопировать WebApp файлы

```bash
# Скопируйте WebApp на сервер
mkdir -p /opt/ege-bot
cp -r /home/user/ege-superbot/WebApp /opt/ege-bot/

# Установите права
chmod -R 755 /opt/ege-bot/WebApp
```

## Проверка

Теперь откройте в браузере:
```
https://xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai/WebApp/teacher/create-assignment.html
```

Или:
```
https://обществонапальцах.рф/WebApp/teacher/create-assignment.html
```

## Автопродление

acme.sh автоматически настраивает cron для продления сертификата каждые 60 дней.

Проверьте cron задачу:
```bash
crontab -l | grep acme
```

Вы должны увидеть что-то вроде:
```
0 0 * * * "/root/.acme.sh"/acme.sh --cron --home "/root/.acme.sh" > /dev/null
```

## Устранение проблем

### Если возникает ошибка "Failed to verify domain"

1. Убедитесь что DNS записи для домена указывают на ваш сервер (193.124.112.38)
2. Проверьте что порт 80 открыт в файрволле:
   ```bash
   ufw allow 80/tcp
   ufw allow 443/tcp
   ```

3. Убедитесь что Nginx слушает порт 80:
   ```bash
   netstat -tlnp | grep :80
   ```

### Альтернативный метод: DNS validation

Если webroot не работает, можно использовать DNS валидацию:

```bash
~/.acme.sh/acme.sh --issue --dns -d xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai

# Скрипт покажет TXT запись которую нужно добавить в DNS
# Добавьте эту запись в вашем DNS провайдере, затем продолжите:

~/.acme.sh/acme.sh --renew -d xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai
```

## Полный скрипт установки

```bash
#!/bin/bash
set -e

echo "=== Установка acme.sh ==="
curl https://get.acme.sh | sh
source ~/.bashrc

echo "=== Настройка Nginx для вебрута ==="
mkdir -p /var/www/html
cat > /etc/nginx/sites-available/temp <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai обществонапальцах.рф;
    root /var/www/html;
    location /.well-known/acme-challenge/ {
        alias /var/www/html/.well-known/acme-challenge/;
    }
}
EOF
ln -sf /etc/nginx/sites-available/temp /etc/nginx/sites-enabled/temp
nginx -t && systemctl reload nginx

echo "=== Получение SSL сертификата ==="
~/.acme.sh/acme.sh --issue -d xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai -w /var/www/html

echo "=== Установка сертификата ==="
mkdir -p /etc/nginx/ssl
~/.acme.sh/acme.sh --install-cert -d xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai \
  --key-file       /etc/nginx/ssl/key.pem  \
  --fullchain-file /etc/nginx/ssl/fullchain.pem \
  --reloadcmd     "systemctl reload nginx"

echo "=== Настройка WebApp Nginx конфигурации ==="
rm -f /etc/nginx/sites-enabled/temp
cp /home/user/ege-superbot/nginx_webapp.conf /etc/nginx/sites-available/webapp
sed -i 's|/etc/letsencrypt/live/.*/fullchain.pem|/etc/nginx/ssl/fullchain.pem|' /etc/nginx/sites-available/webapp
sed -i 's|/etc/letsencrypt/live/.*/privkey.pem|/etc/nginx/ssl/key.pem|' /etc/nginx/sites-available/webapp
ln -sf /etc/nginx/sites-available/webapp /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "=== Копирование WebApp файлов ==="
mkdir -p /opt/ege-bot
cp -r /home/user/ege-superbot/WebApp /opt/ege-bot/
chmod -R 755 /opt/ege-bot/WebApp

echo "=== Готово! ==="
echo "WebApp доступен по адресу:"
echo "https://xn--80aaabfr9bnfdntn4cn1bzd.xn--p1ai/WebApp/teacher/create-assignment.html"
```

Сохраните этот скрипт как `setup_ssl.sh` и запустите:

```bash
chmod +x setup_ssl.sh
./setup_ssl.sh
```
