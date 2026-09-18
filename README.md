# HireVoltz — Next-Gen AI Career & Job Portal Platform

## Project Overview

HireVoltz is an enterprise-grade web-based job portal application designed to connect job seekers and employers through a fast, modern, and highly secure platform.

The application allows users to create accounts, explore job opportunities, and manage their profiles, while employers can manage job-related functionalities through a dedicated dashboard.

---

## Objectives

* Develop a secure job portal system
* Implement OTP-based email verification
* Provide an easy-to-use interface for users and employers
* Enable efficient job search and management

---

## Technologies Used

* Python
* Flask (or relevant backend framework)
* HTML, CSS
* JavaScript
* SQLite / Database

---

## Key Features

* User registration with OTP email verification
* Secure login system
* User dashboard for managing profile
* Employer dashboard for managing activities
* Responsive and user-friendly interface

---

## Working Principle

1. Users register using their email address.
2. An OTP is sent to the registered email for verification.
3. After successful verification, users can log in securely.
4. Users can access the dashboard and manage their activities.
5. Employers can manage job-related functionalities through their dashboard.

---

## Production & Deployment Architecture

### 1. HTTPS Termination & Reverse Proxy
Flask's built-in WSGI server should **never** directly expose or serve production traffic. In production, always terminate HTTPS at a dedicated reverse proxy (such as Nginx, Caddy, AWS ALB, or Cloudflare) and forward requests to an application server (like Gunicorn or uWSGI):

- **Reverse Proxy Requirements**:
  - Terminate TLS 1.2 / TLS 1.3 certificates.
  - Forward client protocol headers: `proxy_set_header X-Forwarded-Proto $scheme;` and `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`.
- **Environment Flags**:
  - Set `FLASK_ENV=production` and `SESSION_COOKIE_SECURE=1` in `.env`.
  - Secure cookies (`Secure; HttpOnly; SameSite=Lax`) and HSTS (`Strict-Transport-Security: max-age=31536000; includeSubDomains`) will automatically be enforced on all responses.

### 2. Rate Limiting & Multi-Worker Redis Configuration
In any multi-process or production deployment (e.g. running multiple Gunicorn or uWSGI workers), `RATELIMIT_STORAGE_URI` **must point to a shared Redis instance** rather than `memory://`:
- **Single Process / Local Dev**: Defaults to `memory://` with in-memory fallback.
- **Multi-Worker / Production**: Set `RATELIMIT_STORAGE_URI=redis://localhost:6379/0` (or `redis://redis:6379/0` in Docker).

```bash
# Example .env configuration for Redis rate limiting
RATELIMIT_STORAGE_URI=redis://localhost:6379/0
```

### 3. Database Least-Privilege Setup (MySQL)
The application user only requires Data Manipulation Language (DML) permissions on the `jobportal_db` database. Never grant administrative privileges (`SUPER`, `FILE`, `GRANT OPTION`, `DROP DATABASE`) to the application user:

```sql
-- Minimal MySQL Permissions
CREATE USER IF NOT EXISTS 'jobportal'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON jobportal_db.* TO 'jobportal'@'localhost';
FLUSH PRIVILEGES;
```

### 4. Dependency Vulnerability Audits
To ensure dependencies remain free of known CVEs, periodically audit `requirements.txt`:
```bash
pip-audit -r requirements.txt
```

### 5. Health Monitoring & Uptime Checks
The application provides a lightweight healthcheck endpoint at `/healthz` (also aliased at `/api/healthz` and `/api/health`) that verifies database connectivity and returns latency metrics without leaking error messages:
- **Status 200**: Healthy (`{"status": "healthy", "services": {"database": {"status": "healthy", "latency_ms": 1.2}}}`)
- **Status 503**: Unhealthy (`{"status": "unhealthy", "services": {"database": {"status": "unreachable"}}}`)

Recommended: Integrate with Prometheus, Datadog, or external uptime monitors (UptimeRobot, BetterStack) and alert on consecutive 503s or abnormal failed-login rate spikes.

### 6. Database Backups & Disaster Recovery
For the comprehensive MySQL backup strategy (including daily `mysqldump` commands, 7-day daily / 4-week GFS retention, AWS S3/GCS offsite replication, and tested restoration procedures), see [BACKUPS.md](BACKUPS.md).

---

## Security Testing
Run the dedicated core security test suite covering authentication bypass, authorization boundaries, CSRF rejection, SQL injection resistance, and 3-attempt account lockout:
```bash
python -m pytest tests/security/ -v --tb=short
```

---

## Running with Docker Compose
The included `docker-compose.yml` automatically provisions MySQL 8.0, Redis 7 (Alpine), the web application, and background workers with non-root execution and localhost-only database binding:
```bash
docker-compose up --build
```

---

## Security Note

Sensitive information such as email credentials, database passwords, and secret keys are not included in this repository. Ensure all required environment variables in `.env` (`FLASK_SECRET_KEY`, `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`) are properly populated prior to startup.


