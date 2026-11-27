import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database.connection import connect

class ConnectionTests(unittest.TestCase):
 def test_persistence_and_rollback(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'nested/db.sqlite3'
   with connect(path) as db:
    db.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY)')
    db.execute('INSERT INTO sample VALUES (1)')
   try:
    with connect(path) as db:
     db.execute('INSERT INTO sample VALUES (2)')
     raise RuntimeError('rollback')
   except RuntimeError: pass
   with connect(path) as db:
    self.assertEqual(db.execute('SELECT count(*) FROM sample').fetchone()[0],1)
 def test_foreign_keys(self):
  with tempfile.TemporaryDirectory() as folder:
   with connect(Path(folder)/'db.sqlite3') as db:
    db.execute('CREATE TABLE parent (id INTEGER PRIMARY KEY)')
    db.execute('CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))')
    with self.assertRaises(sqlite3.IntegrityError):
     db.execute('INSERT INTO child VALUES (123)')

if __name__=='__main__': unittest.main()
