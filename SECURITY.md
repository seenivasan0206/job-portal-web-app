# Security Policy

## Secret Management

All secrets for HireVoltz are loaded exclusively from environment variables
via a `.env` file (loaded by `python-dotenv`). **No secret is ever hardcoded**
in source code.

| Variable          | Purpose                    | Required |
|-------------------|----------------------------|----------|
| `FLASK_SECRET_KEY`| Session signing key        | Yes      |
| `DB_USER`         | MySQL username             | Yes      |
| `DB_PASSWORD`     | MySQL password             | Yes      |
| `DB_HOST`         | MySQL host (default: localhost) | No  |
| `DB_NAME`         | MySQL database name        | Yes      |
| `EMAIL_ADDRESS`   | Gmail address for OTP emails | Yes    |
| `EMAIL_PASSWORD`  | Google App Password        | Yes      |
| `MAX_UPLOAD_MB`   | Resume upload size limit   | No (default 5) |

### Fail-Loud Behaviour

On startup, `app.py` checks every required variable and raises
`RuntimeError` if any are missing. **There are no insecure fallbacks** —
the app will not start without proper configuration.

## Rotating the Gmail App Password

If you suspect the Google App Password has been exposed:

1. Go to your Google Account → Security → **2-Step Verification** → **App passwords**.
2. Find the app password previously used for HireVoltz and **revoke** it.
3. Generate a new app password for the same Gmail account.
4. Update `EMAIL_PASSWORD` in your `.env` file.
5. Restart the Flask application.

> **Never** commit the real `.env` file. Run `git status` before committing
> to ensure `.env` is ignored (it is included in `.gitignore`).

## OTP Expiry

One-time passwords expire 2 minutes after creation. Expired OTP rows are
automatically cleaned up on each `verify_otp` call.

## Reporting a Vulnerability

If you discover a security issue, please open a private issue on GitHub
or contact the maintainers directly.
