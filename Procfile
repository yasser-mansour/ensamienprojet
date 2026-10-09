release: python manage.py migrate --noinput && python manage.py createcachetable
web: gunicorn config.wsgi --workers ${WEB_CONCURRENCY:-3} --threads 4 --timeout 30 --max-requests 2000 --max-requests-jitter 200 --access-logfile -
