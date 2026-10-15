import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class TaskStore:
    """Small local transactions. Deploy this MVP with exactly one worker process."""
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / 'tasks.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, status TEXT NOT NULL, progress REAL,
                provider TEXT NOT NULL, remote_id TEXT, images TEXT NOT NULL,
                error TEXT, created_at TEXT NOT NULL)''')

    def connect(self):
        return sqlite3.connect(self.database, timeout=10)

    def create(self, task_id, provider, images):
        with self.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (task_id, 'queued', None, provider, None, json.dumps(images),
                        None, datetime.now(timezone.utc).isoformat()))

    def get(self, task_id):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            return dict(row) if row else None

    def update(self, task_id, **fields):
        assert set(fields) <= {'status', 'progress', 'remote_id', 'error'}
        with self.connect() as db:
            db.execute('UPDATE tasks SET ' + ','.join(f'{k}=?' for k in fields) +
                       ' WHERE task_id=?', (*fields.values(), task_id))

    def pending(self):
        with self.connect() as db:
            return [r[0] for r in db.execute(
                "SELECT task_id FROM tasks WHERE status IN ('queued','processing') ORDER BY created_at")]
