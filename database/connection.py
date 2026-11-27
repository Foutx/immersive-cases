"""Local SQLite connection. No external packages or database server required."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def database_path():
    configured = os.environ.get('DATABASE_PATH', 'data/immersive_cases.sqlite3')
    if not configured.strip():
        raise ValueError('DATABASE_PATH cannot be empty')
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / path

@contextmanager
def connect(path=None):
    target = Path(path) if path is not None else database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA journal_mode = WAL')
        with connection:
            yield connection
    finally:
        connection.close()
