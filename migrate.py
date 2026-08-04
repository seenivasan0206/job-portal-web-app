"""One-time migration: hash any plaintext passwords still stored in the
user and employee tables.

This script can only be run with the --confirm flag to prevent accidental
re-execution:

    python migrate.py --confirm

Requires a .env (or the DB defaults) so it can connect.

Werkzeug's check_password_hash cannot verify a plaintext value, so we
detect plaintext by attempting to parse the stored value as a hash
(format is always "pbkdf2:sha256$..." or "scrypt$..."). Anything that
does not match that format is treated as plaintext and re-hashed.
"""
import os
import sys
from dotenv import load_dotenv
import mysql.connector
from werkzeug.security import generate_password_hash

load_dotenv()

db_config = {
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', 'mysql'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'dream_jobs0'),
}


def looks_hashed(pw):
    # Werkzeug hashes start with the method name, e.g. "pbkdf2:sha256$..."
    return bool(pw) and ('$' in pw) and not pw.startswith('$plain$')


def migrate(table, id_col):
    conn = mysql.connector.connect(**db_config)
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(f"SELECT {id_col}, password FROM {table}")
        rows = cur.fetchall()
        updated = 0
        for r in rows:
            pw = r['password']
            if pw and not looks_hashed(pw):
                cur.execute(
                    f"UPDATE {table} SET password = %s WHERE {id_col} = %s",
                    (generate_password_hash(pw), r[id_col]),
                )
                updated += 1
        conn.commit()
        print(f"{table}: {updated} plaintext password(s) hashed.")
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    if '--confirm' not in sys.argv:
        print("This migration modifies passwords in the database.")
        print("To proceed, run: python migrate.py --confirm")
        sys.exit(1)
    migrate('user', 'id')
    migrate('employee', 'id')
    print("Migration complete.")
