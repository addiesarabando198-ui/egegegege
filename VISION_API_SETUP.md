# Настройка Yandex Vision API для OCR

Для работы функции распознавания текста с фотографий (OCR) необходимо настроить права доступа к Yandex Vision API.

## Проблема
При попытке использовать OCR возникает ошибка:
```
Vision API error: 403 - Permission denied
```

Это означает, что у вашего API ключа/сервисного аккаунта нет прав на использование Vision API.

## Решение

### Способ 1: Через веб-интерфейс Yandex Cloud (рекомендуется)

1. **Откройте Yandex Cloud Console**
   - Перейдите на https://console.cloud.yandex.ru/

2. **Найдите ваш сервисный аккаунт**
   - В меню слева выберите "IAM" → "Сервисные аккаунты"
   - Найдите сервисный аккаунт, который используется для получения API ключа
   - Обычно это аккаунт, для которого был создан `YANDEX_GPT_API_KEY`

3. **Добавьте роль для Vision API**
   - Откройте страницу сервисного аккаунта
   - Перейдите на вкладку "Права доступа"
   - Нажмите кнопку "Назначить роли"
   - В списке ролей найдите и выберите одну из:
     - **`ai.vision.user`** (минимально необходимая роль для OCR)
     - **`editor`** (если нужны расширенные права)
   - Нажмите "Сохранить"

4. **Перезапустите бота**
   ```bash
   sudo systemctl restart ваш-бот.service
   ```

### Способ 2: Через Yandex Cloud CLI

Если у вас установлен `yc` CLI:

```bash
# Получите ID вашего folder
yc config list

# Получите ID сервисного аккаунта
yc iam service-account list

# Назначьте роль ai.vision.user
yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role ai.vision.user \
  --service-account-id <SERVICE_ACCOUNT_ID>

# Или назначьте роль editor (более широкие права)
yc resource-manager folder add-access-binding <FOLDER_ID> \
  --role editor \
  --service-account-id <SERVICE_ACCOUNT_ID>
```

### Способ 3: Создание нового API ключа с правильными правами

Если предыдущие способы не помогли:

1. Создайте новый сервисный аккаунт с ролью `ai.vision.user`
2. Создайте для него API ключ
3. Обновите `.env`:
   ```env
   YANDEX_GPT_API_KEY=новый_api_ключ
   YANDEX_GPT_FOLDER_ID=ваш_folder_id
   ```
4. Перезапустите бота

## Проверка прав

После настройки прав проверьте, что у сервисного аккаунта есть необходимые роли:

```bash
yc iam service-account list-access-bindings <SERVICE_ACCOUNT_ID>
```

Вы должны увидеть в списке роль `ai.vision.user` или `editor`.

## Необходимые роли

Минимально необходимые роли для работы бота с OCR:
- `ai.languageModels.user` - для YandexGPT (проверка ответов)
- `ai.vision.user` - для Vision API (OCR)

## Работа без OCR

Если не хотите настраивать Vision API прямо сейчас:
- Бот будет продолжать работать
- При попытке отправить фото пользователь получит сообщение:
  ```
  OCR сервис временно недоступен
  Для работы OCR требуется настроить права доступа в Yandex Cloud.
  Пожалуйста, введите текст вручную.
  ```
- Пользователи смогут использовать текстовый ввод или загрузку документов (PDF, DOCX, TXT)

## Дополнительная информация

Официальная документация:
- [Yandex Vision API](https://cloud.yandex.ru/docs/vision/)
- [Управление доступом в Vision](https://cloud.yandex.ru/docs/vision/security/)
- [Роли в Yandex Cloud](https://cloud.yandex.ru/docs/iam/concepts/access-control/roles)

## Тарификация

Yandex Vision API тарифицируется отдельно от YandexGPT:
- Первые 1000 запросов в месяц - бесплатно
- Далее ~0.8 ₽ за запрос

Подробнее: https://cloud.yandex.ru/docs/vision/pricing
