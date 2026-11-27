"""Transactional, forward-only migrations: python -m database.migrate."""
import hashlib
import sqlite3
from pathlib import Path
from .connection import connect

MIGRATIONS = Path(__file__).with_name('migrations')

def statements(sql):
    buffer = ''
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ''
    if buffer.strip():
        raise ValueError('Incomplete SQL migration')

def migrate(path=None, migrations_dir=MIGRATIONS):
    files = sorted(Path(migrations_dir).glob('[0-9]*_*.sql'))
    applied = []
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations '
                   '(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL '
                   "DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
        previous = dict(db.execute('SELECT version,checksum FROM schema_migrations'))
        if set(previous) - {f.name for f in files}:
            raise ValueError('Database contains unknown migrations; use matching application version')
        for file in files:
            raw = file.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            if file.name in previous:
                if previous[file.name] != checksum:
                    raise ValueError(f'Applied migration changed: {file.name}')
                continue
            if previous and file.name < max(previous):
                raise ValueError('Cannot insert a migration before an applied version')
            for statement in statements(raw.decode('utf-8-sig')):
                db.execute(statement)
            db.execute('INSERT INTO schema_migrations(version,checksum) VALUES(?,?)',(file.name,checksum))
            applied.append(file.name)
    return applied

def main():
    try:
        applied = migrate()
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise SystemExit(f'Migration failed: {exc}')
    print('Applied: ' + ', '.join(applied) if applied else 'Schema is up to date')

if __name__ == '__main__': main()
