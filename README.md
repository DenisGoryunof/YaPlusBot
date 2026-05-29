# YaPlusBot - Telegram бот для управления подписками

## Деплой на Fly.io через GitHub Actions

### 1. Подготовка

1. Создайте аккаунт на [Fly.io](https://fly.io)
2. Установите Fly CLI локально для тестирования
3. Форкните или клонируйте этот репозиторий

### 2. Настройка GitHub Secrets

В репозитории GitHub перейдите в Settings → Secrets and variables → Actions и добавьте:

- `FLY_API_TOKEN` - API токен Fly.io (получить командой `flyctl auth token`)
- `BOT_TOKEN` - Токен вашего Telegram бота
- `ADMIN_ID` - Ваш Telegram ID (администратор)
- `GROUP_ID` - ID группы (опционально)

### 3. Автоматический деплой

При пуше в ветку `main` GitHub Actions автоматически задеплоит бота на Fly.io.

### 4. Ручной деплой

```bash
# Локально
fly deploy

# Или через GitHub Actions вручную
# Actions → Deploy to Fly.io → Run workflow