# Deployment: `ensamien.yassermansour.com`

> Nothing has been deployed yet. These steps need your accounts and your approval. They use
> a **new** Heroku app and a **new** database, and do not touch any existing app or database.

## What is already prepared

* `requirements.txt` (pinned), `.python-version` (3.13), and a `Procfile` with a release phase
  (`migrate` + `createcachetable`) and a gunicorn web process.
* `config/settings.py` reads everything from the environment (see `.env.example`). It refuses to start
  without `DJANGO_SECRET_KEY` when `DEBUG` is off.
* WhiteNoise serves compressed, hashed static files; no CDN or S3 is needed.
* `GET /healthz/` checks the database and returns `{"status": "ok"}`. It is exempt from the HTTPS redirect.
* `python manage.py check --deploy` passes. The only two silenced warnings are HSTS
  `includeSubDomains`/`preload`, left off on purpose so other `*.yassermansour.com` sites are not affected.

## Heroku (recommended)

```bash
heroku create ensamien-energy-lab            # new app; any free name
heroku addons:create heroku-postgresql:essential-0 -a ensamien-energy-lab   # new, separate database (paid add-on; check pricing before running)

heroku config:set -a ensamien-energy-lab \
  DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  DJANGO_ALLOWED_HOSTS="ensamien.yassermansour.com,ensamien-energy-lab.herokuapp.com" \
  DJANGO_CSRF_TRUSTED_ORIGINS="https://ensamien.yassermansour.com,https://ensamien-energy-lab.herokuapp.com" \
  PUBLIC_BASE_URL="https://ensamien.yassermansour.com" \
  DJANGO_SECURE_SSL=1 \
  WEB_CONCURRENCY=3

git push heroku <branch>:main                 # release phase runs migrations (and loads the missions)
heroku run -a ensamien-energy-lab python manage.py create_host --email you@example.com
```

### Custom domain

```bash
heroku domains:add ensamien.yassermansour.com -a ensamien-energy-lab
heroku certs:auto:enable -a ensamien-energy-lab
```

Heroku prints a DNS target. At your DNS provider, add a **CNAME** record `ensamien` → that target.
This is a manual step for you; it was not done.
Then check: `curl https://ensamien.yassermansour.com/healthz/`.

### Sizing

Peak load is about 12 requests per second (10 phones + host + projector polling every second).
The load test in `docs/TEST_REPORT.md` shows this is far within one small dyno and the smallest
Postgres plan. Use one web dyno with `WEB_CONCURRENCY=3` (3 gunicorn workers × 4 threads).
**Do not use a dyno type that sleeps** for the presentation, because the first request after
sleeping is slow.

## Other hosts (VPS, Render, Railway, Fly…)

Any platform that runs `gunicorn config.wsgi` behind HTTPS works:

1. Set the same environment variables (`DATABASE_URL` must point to PostgreSQL).
2. On deploy: `python manage.py migrate && python manage.py createcachetable && python manage.py collectstatic --noinput`.
3. The proxy must send `X-Forwarded-Proto: https` (used for secure-request detection).

## Before the presentation

* Create the host account on production and sign in once.
* Create a **test session** and join from two phones on the classroom Wi-Fi (or mobile data).
* Open the projector window on the projector, press **F** for full screen, and check the QR opens the site.
* Finish the test session. It stays in history and its code becomes reusable. Then create
  the real session just before class.
* A session's join code expires 12 hours after creation (`SESSION_LIFETIME_HOURS`).

## Rollback / safety

* Each session is independent and history is never deleted by the app (only "archived").
* Back up the database before and after the presentation if you want a copy:
  `heroku pg:backups:capture -a ensamien-energy-lab`.
