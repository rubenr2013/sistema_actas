# Dockerfile para Railway
FROM python:3.11-slim

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias Python
COPY sistema_actas/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el proyecto
COPY sistema_actas/ .

# Crear directorio para archivos estáticos
RUN mkdir -p staticfiles

# Recolectar archivos estáticos
RUN python manage.py collectstatic --noinput

# Exponer puerto
EXPOSE 8000

# Comando para iniciar la aplicación
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn sistema_actas.wsgi:application --bind 0.0.0.0:8000"]
