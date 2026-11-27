"""Create/check local SQLite: python -m database.check"""
import sys
import sqlite3
from .connection import connect, database_path

def main():
    try:
        with connect() as db:
            result = db.execute('SELECT 1').fetchone()[0]
            db.execute('CREATE TEMP TABLE connection_probe (value INTEGER NOT NULL)')
            db.execute('INSERT INTO connection_probe VALUES (1)')
            assert db.execute('SELECT value FROM connection_probe').fetchone()[0] == 1
        print(f'SQLite OK: {database_path()} (SELECT 1={result}, write OK)')
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'Database check failed: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__': sys.exit(main())

