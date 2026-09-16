# AGENTS.md

## Commands

### Install dependencies
```
pip install -r requirements.txt
pip install -r requirements-test.txt
```

### Syntax check
```
python -c "import app; print('app.py imports OK')"
```

### Run tests
```
python -m pytest tests/ -v --tb=short --timeout=120
python -m pytest tests/security/ -v --tb=short
```

### Lint
```
flake8 app.py migrate.py --max-line-length=120 --statistics
```

### Run locally
```
python app.py
```

### Run with Docker
```
docker-compose up --build
```

### Reset admin password (migrate plaintext)
```
python migrate.py --confirm
```

## Environment Variables
Required (fail loudly if missing):
- `FLASK_SECRET_KEY`
- `EMAIL_ADDRESS`
- `EMAIL_PASSWORD`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `DB_HOST`

Optional:
- `FLASK_DEBUG=1` — enable debug mode
- `FLASK_ENV=production` — enable secure cookies
- `SESSION_COOKIE_SECURE=1` — enable secure cookies
- `STRICT_SESSION_FINGERPRINT=1` — enable IP-based session binding (disabled by default; enabling binds sessions to IP, which may cause logouts for mobile/VPN users)
- `OTP_TTL_SECONDS=120` — OTP expiry (default 120 = 2 min)
- `MAX_UPLOAD_MB=5` — file upload size limit
- `RATELIMIT_STORAGE_URI=memory://` — Flask-Limiter storage
- `CRON_SECRET=secret` — secret for cron job authentication

