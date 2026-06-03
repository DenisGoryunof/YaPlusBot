FROM python:3.11-slim

WORKDIR /app

# Создаем директорию для данных (Coolify будет монтировать сюда том)
RUN mkdir -p /data

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY bot.py .

# Запускаем бота
CMD ["python", "-u", "bot.py"]
