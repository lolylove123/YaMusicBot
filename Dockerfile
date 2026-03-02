# 1. Используем официальный образ Python
FROM python:3.11-slim

# 2. Устанавливаем системные зависимости (ffmpeg и библиотеки для звука)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libffi-dev libnacl-dev python3-dev && \
    rm -rf /var/lib/apt/lists/*

# 3. Устанавливаем рабочую директорию
WORKDIR /app

# 4. Копируем файл зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем весь остальной код бота
COPY . .

# 6. Создаем папку для кэша и даем права (важно для хостинга!)
RUN mkdir -p cache && chmod 777 cache

# 7. Запуск бота
CMD ["python", "bot.py"]