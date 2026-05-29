FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY bot.py .
COPY .env .

# Создаем директорию для постоянного хранилища
RUN mkdir -p /persistent

# Запускаем бота
CMD ["python", "bot.py"]