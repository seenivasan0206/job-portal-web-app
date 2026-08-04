# AGENTS.md

## Commands

### Install dependencies
```
pip install -r requirements.txt
pip install pytest pytest-flask flake8
```

### Syntax check
```
python -c "import app; print('app.py imports OK')"
```

### Run tests
```
python -m pytest tests/ -v --tb=short
```

### Lint
```
flake8 app.py migrate.py --max-line-length=120 --statistics
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
- `OTP_TTL_SECONDS=120` — OTP expiry (default 120 = 2 min)
