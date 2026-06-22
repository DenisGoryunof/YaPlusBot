FROM python:3.11-slim

# Настройка DNS заранее (для надежности)
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf && \
    echo "nameserver 1.1.1.1" >> /etc/resolv.conf && \
    echo "nameserver 77.88.8.8" >> /etc/resolv.conf

# Добавляем хосты напрямую
RUN echo "149.154.167.220 api.telegram.org" >> /etc/hosts && \
    echo "149.154.167.99 telegram.org" >> /etc/hosts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаем директорию для данных
RUN mkdir -p /data

# Используем переменную окружения для порта
ENV PORT=8080

CMD ["python", "bot.py"]