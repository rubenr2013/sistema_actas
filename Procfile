web: cd sistema_actas && gunicorn sistema_actas.wsgi --log-file -
release: cd sistema_actas && python manage.py migrate --noinput && python manage.py collectstatic --noinput
