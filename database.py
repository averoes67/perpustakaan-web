import os
import sqlite3
import hashlib
import secrets
import shutil
from datetime import datetime, timedelta
from urllib.parse import urlparse

def get_database_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    return url if url else None

def is_postgres():
    url = get_database_url()
    return bool(url and url.startswith("postgres"))

def get_sqlite_path():
    # Di Vercel / AWS Lambda, root filesystem read-only. Writable dir adalah /tmp
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        tmp_db = "/tmp/library.db"
        local_seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")
        if not os.path.exists(tmp_db) and os.path.exists(local_seed):
            try:
                shutil.copyfile(local_seed, tmp_db)
            except Exception:
                pass
        return tmp_db
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.db")

class PostgresRow:
    """Wrapper baris data agar kompatibel dengan sqlite3.Row (akses via row['col'] dan row[0])"""
    def __init__(self, data_dict, tuple_values):
        self._data = data_dict
        self._tuple = tuple_values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._tuple[key]
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._tuple)

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, params=None):
        if params is not None:
            # Ganti placeholder '?' ke '%s' untuk PostgreSQL
            query = query.replace("?", "%s")
            return self.cursor.execute(query, params)
        return self.cursor.execute(query)

    def executemany(self, query, seq_of_params):
        query = query.replace("?", "%s")
        return self.cursor.executemany(query, seq_of_params)

    def _convert_row(self, row):
        if row is None:
            return None
        col_names = [desc[0] for desc in self.cursor.description]
        d = dict(zip(col_names, row))
        return PostgresRow(d, row)

    def fetchone(self):
        row = self.cursor.fetchone()
        return self._convert_row(row)

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        col_names = [desc[0] for desc in self.cursor.description]
        return [PostgresRow(dict(zip(col_names, r)), r) for r in rows]

    @property
    def lastrowid(self):
        return getattr(self.cursor, "lastrowid", None)

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self.conn.cursor())

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

def connect_postgres(url):
    # Pastikan prefix postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    # 1. Coba dengan psycopg2 terlebih dahulu
    try:
        import psycopg2
        conn = psycopg2.connect(url, sslmode="require", connect_timeout=10)
        return PostgresConnectionWrapper(conn)
    except ImportError:
        pass

    # 2. Fallback ke pg8000 (Pure Python, tidak butuh compiler C atau libpq)
    import pg8000.native
    import ssl
    parsed = urlparse(url)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    class Pg8000CursorWrapper:
        def __init__(self, client):
            self.client = client
            self._last_result = []
            self._idx = 0
            self.description = []

        def execute(self, query, params=None):
            # pg8000 menggunakan format :1, :2 atau parameter langsung
            # Kita konversi ? ke param binding pg8000
            if params is None:
                params = ()
            # Ganti ? dengan format pg8000 native
            q = query
            parts = q.split("?")
            if len(parts) > 1:
                new_q = parts[0]
                for i, p in enumerate(parts[1:]):
                    new_q += f":param_{i}" + p
                param_dict = {f"param_{i}": val for i, val in enumerate(params)}
                res = self.client.run(new_q, **param_dict)
            else:
                res = self.client.run(q)

            self._last_result = res if res else []
            self._idx = 0
            if self.client.columns:
                self.description = [(c["name"], None) for c in self.client.columns]
            else:
                self.description = []

        def executemany(self, query, seq_of_params):
            for p in seq_of_params:
                self.execute(query, p)

        def fetchone(self):
            if self._idx < len(self._last_result):
                row = self._last_result[self._idx]
                self._idx += 1
                col_names = [d[0] for d in self.description]
                d = dict(zip(col_names, row))
                return PostgresRow(d, row)
            return None

        def fetchall(self):
            rows = self._last_result[self._idx:]
            self._idx = len(self._last_result)
            col_names = [d[0] for d in self.description]
            return [PostgresRow(dict(zip(col_names, r)), r) for r in rows]

        @property
        def lastrowid(self):
            return None

    class Pg8000ConnectionWrapper:
        def __init__(self, client):
            self.client = client

        def cursor(self):
            return Pg8000CursorWrapper(self.client)

        def commit(self):
            pass  # pg8000 native autocommits outside transaction

        def rollback(self):
            pass

        def close(self):
            try:
                self.client.close()
            except Exception:
                pass

    client = pg8000.native.Connection(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        ssl_context=ssl_context,
        timeout=10
    )
    return Pg8000ConnectionWrapper(client)

def get_db():
    if is_postgres():
        return connect_postgres(get_database_url())
    else:
        conn = sqlite3.connect(get_sqlite_path())
        conn.row_factory = sqlite3.Row
        return conn

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(plain: str, stored: str) -> bool:
    try:
        salt, hashed = stored.split(":")
        return hashlib.sha256((salt + plain).encode()).hexdigest() == hashed
    except Exception:
        return False

def init_db():
    if is_postgres():
        return  # Di Supabase skema sudah dibuat via SQL Editor

    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            status TEXT DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT DEFAULT 'visitor',
            member_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isbn TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            publisher TEXT,
            category TEXT NOT NULL,
            year INTEGER,
            shelf_location TEXT,
            cover_url TEXT,
            total_copies INTEGER DEFAULT 1,
            available_copies INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_code TEXT UNIQUE NOT NULL,
            member_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            borrow_date DATE NOT NULL,
            due_date DATE NOT NULL,
            return_date DATE,
            status TEXT DEFAULT 'BORROWED',
            fine_amount REAL DEFAULT 0.0,
            fine_paid INTEGER DEFAULT 0,
            notes TEXT,
            FOREIGN KEY (member_id) REFERENCES members (id),
            FOREIGN KEY (book_id) REFERENCES books (id)
        )
        """)

        conn.commit()
        conn.close()
    except Exception as e:
        # Jika gagal saat init_db di read-only filesystem, jangan crash aplikasi
        print(f"init_db notice: {e}")
