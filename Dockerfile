FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home cockpit && mkdir -p /app/daten && chown -R cockpit /app/daten
USER cockpit

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput -v0 && gunicorn cockpit.wsgi --bind 0.0.0.0:8000 --workers 2"]
