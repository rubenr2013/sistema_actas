# Dockerfile para Railway
FROM python:3.11-slim

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

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

# Crear directorios necesarios
RUN mkdir -p staticfiles logs media

# Recolectar archivos estáticos (con SECRET_KEY temporal para este paso)
RUN SECRET_KEY=temp-key-for-collectstatic python manage.py collectstatic --noinput

# Exponer puerto (Railway usa la variable PORT)
EXPOSE $PORT

# Comando para iniciar la aplicación
# Railway provee PORT, usamos ese valor
CMD sh -c "python manage.py migrate --noinput && gunicorn sistema_actas.wsgi:application --bind 0.0.0.0:\$PORT --workers 2 --timeout 120 --log-level info"
