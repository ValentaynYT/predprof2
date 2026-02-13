# Dockerfile
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё приложение
COPY . .

# Создаём папку для аватарок (на случай, если её нет)
RUN mkdir -p static/avatars

# Открываем порт
EXPOSE 5000

# Запускаем приложение
CMD ["python", "app.py"]