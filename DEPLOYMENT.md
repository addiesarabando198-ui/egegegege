# Инструкция по деплою Teacher WebApp API

## Шаг 1: Копирование файлов на сервер

Скопируйте обновленные файлы на сервер:

```bash
# На сервере, находясь в /opt/ege-bot
git pull origin claude/create-teacher-backend-api-J21Ge
```

## Шаг 2: Установка systemd сервиса

```bash
# Копируем systemd сервис файл
sudo cp /opt/ege-bot/teacher-api.service /etc/systemd/system/teacher-api.service

# Перезагружаем systemd
sudo systemctl daemon-reload

# Если сервис уже запущен, перезапускаем его
sudo systemctl restart teacher-api

# Если нет - включаем и запускаем
sudo systemctl enable teacher-api
sudo systemctl start teacher-api

# Проверяем статус
sudo systemctl status teacher-api
```

## Шаг 3: Обновление конфигурации nginx

```bash
# Создаем резервную копию
sudo cp /etc/nginx/sites-available/webapp /etc/nginx/sites-available/webapp.backup

# Копируем новую конфигурацию
sudo cp /opt/ege-bot/nginx-webapp.conf /etc/nginx/sites-available/webapp

# Проверяем конфигурацию
sudo nginx -t

# Если проверка успешна, перезагружаем nginx
sudo systemctl reload nginx
```

## Шаг 4: Проверка работы

### Health Check

```bash
curl https://обществонапальцах.рф/health
```

Должно вернуть:
```json
{"status":"healthy","service":"teacher-webapp-api"}
```

### Swagger UI

Откройте в браузере:
```
https://обществонапальцах.рф/docs
```

### ReDoc

```
https://обществонапальцах.рф/redoc
```

### OpenAPI JSON

```
https://обществонапальцах.рф/openapi.json
```

## Шаг 5: Просмотр логов

```bash
# Логи API сервиса
sudo journalctl -u teacher-api -f

# Логи nginx
sudo tail -f /var/log/nginx/webapp_error.log
sudo tail -f /var/log/nginx/webapp_access.log
```

## Устранение неполадок

### API не запускается

```bash
# Проверяем статус
sudo systemctl status teacher-api

# Смотрим логи
sudo journalctl -u teacher-api -n 100

# Проверяем что порт 8000 свободен
sudo lsof -i :8000
```

### Swagger UI не загружается

1. Проверьте что API запущен:
```bash
curl http://127.0.0.1:8000/docs
```

2. Проверьте nginx логи:
```bash
sudo tail -f /var/log/nginx/webapp_error.log
```

3. Проверьте что заголовки прокси работают:
```bash
curl -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/openapi.json
```

### Nginx ошибки

```bash
# Тест конфигурации
sudo nginx -t

# Перезапуск nginx
sudo systemctl restart nginx
```

## Обновление API

При обновлении кода:

```bash
cd /opt/ege-bot
git pull
sudo systemctl restart teacher-api
```

## Мониторинг

Рекомендуется настроить мониторинг для:
- Статус сервиса: `systemctl is-active teacher-api`
- Health endpoint: `curl https://обществонапальцах.рф/health`
- Использование памяти: `systemctl status teacher-api`
