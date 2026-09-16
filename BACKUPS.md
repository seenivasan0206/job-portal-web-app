# Database Backup & Disaster Recovery Strategy

This document outlines the database backup, retention, and disaster recovery procedures for SecureHire (MySQL).

---

## 1. Backup Architecture & Frequency

To guarantee business continuity and minimize Recovery Point Objective (RPO) and Recovery Time Objective (RTO):
- **Full Database Dumps**: Executed **daily** during off-peak hours (e.g. 02:00 UTC).
- **Point-in-Time Recovery (PITR)**: MySQL Binary Logging (`binlog`) enabled for granular transaction log replays.
- **Consistency**: All dumps use `--single-transaction` to ensure non-blocking consistency without locking InnoDB tables.

---

## 2. Backup Execution Commands

### Daily Full Backup (Compressed)
```bash
# Environment variables loaded from .env
mysqldump \
  --host="${DB_HOST:-localhost}" \
  --user="${DB_USER}" \
  --password="${DB_PASSWORD}" \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  "${DB_NAME}" | gzip -9 > "/var/backups/mysql/securehire_$(date +%Y%m%d_%H%M%S).sql.gz"
```

### Dockerized MySQL Backup (when running via Docker Compose)
```bash
docker-compose exec -T db mysqldump \
  -u root \
  -p"${DB_PASSWORD}" \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  "${DB_NAME:-jobportal_db}" | gzip -9 > "./backups/backup_$(date +%Y%m%d_%H%M%S).sql.gz"
```

---

## 3. Automated Daily Backup Script (`backup.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/var/backups/mysql"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/securehire_${DATE}.sql.gz"
S3_BUCKET="s3://securehire-database-backups-prod"

mkdir -p "${BACKUP_DIR}"

# 1. Create compressed dump
mysqldump \
  --host="${DB_HOST}" \
  --user="${DB_USER}" \
  --password="${DB_PASSWORD}" \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  "${DB_NAME}" | gzip -9 > "${BACKUP_FILE}"

# 2. Upload to secure off-site object storage (AWS S3 / GCS)
aws s3 cp "${BACKUP_FILE}" "${S3_BUCKET}/${DATE}/" --sse aws:kms

# 3. Apply Local Retention: Purge backups older than 7 days
find "${BACKUP_DIR}" -type f -name "*.sql.gz" -mtime +7 -delete

echo "[+] Backup completed and uploaded: ${BACKUP_FILE}"
```

---

## 4. Retention Policy (Grandfather-Father-Son / GFS)

| Tier | Retention Period | Storage Location |
|---|---|---|
| **Daily Backups** | 7 Days | Local disk + Encrypted Object Storage (S3 / GCS) |
| **Weekly Backups** | 4 Weeks | Encrypted Object Storage |
| **Monthly Backups** | 12 Months | Encrypted Object Storage (Glacier / Coldline) |
| **Annual Archives** | 7 Years | Cold Storage / Compliance Vault |

### Object Storage Lifecycle Policy (AWS S3 Example)
- Move objects to **S3 Standard-IA** after 30 days.
- Move objects to **S3 Glacier Flexible Retrieval** after 90 days.
- Expire / Delete non-archived dumps after 365 days.

---

## 5. Restoration & Recovery Procedures

### Standard Restoration from Compressed Dump
```bash
# 1. Decompress and pipe directly into MySQL
gunzip < "/var/backups/mysql/securehire_20260910_020000.sql.gz" | mysql \
  --host="${DB_HOST:-localhost}" \
  --user="${DB_USER}" \
  --password="${DB_PASSWORD}" \
  "${DB_NAME}"
```

### Docker Compose Restoration
```bash
# 1. Restore into running db container
gunzip < "./backups/backup_20260910_020000.sql.gz" | docker-compose exec -T db mysql \
  -u root \
  -p"${DB_PASSWORD}" \
  "${DB_NAME:-jobportal_db}"
```

---

## 6. Disaster Recovery & Verification Drills

1. **Automated Monthly Restore Test**: A scheduled staging job downloads the latest S3 backup, restores it to an isolated test database, and runs the automated test suite (`pytest tests/`) against the restored data.
2. **Checksum Integrity**: SHA256 hashes generated alongside each dump file before upload to verify zero corruption during transit.
3. **Restricted Access**: Production database credentials and backup storage buckets must strictly require IAM role isolation and multi-factor authentication (MFA).
