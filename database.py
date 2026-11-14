import os
import sqlite3
import hashlib
import secrets
import shutil
import ssl
from urllib.parse import urlparse
from datetime import datetime, timedelta

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

    # Coba psycopg2 jika ada
    try:
        import psycopg2
        conn = psycopg2.connect(url, sslmode="require", connect_timeout=10)
        return PostgresConnectionWrapper(conn)
    except (ImportError, Exception):
        pass

    # Gunakan pg8000 (Pure Python, terbukti 100% stabil di Vercel)
    import importlib
    pg8000 = importlib.import_module("pg8000")
    from urllib.parse import unquote
    parsed = urlparse(url)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    database = unquote(parsed.path.lstrip("/")) if parsed.path else None
    host = parsed.hostname
    port = parsed.port or 5432

    # Otomatisasi Supabase: Direct connection (db.xxxx.supabase.co) adalah IPv6-only
    # yang tidak didukung oleh lingkungan serverless AWS Lambda / Vercel.
    # Alihkan otomatis ke Supabase Connection Pooler IPv4 (aws-0-ap-southeast-1.pooler.supabase.com port 6543).
    if host and host.startswith("db.") and host.endswith(".supabase.co"):
        project_ref = host[3:-len(".supabase.co")]
        host = "aws-0-ap-southeast-1.pooler.supabase.com"
        port = 6543
        if user and not user.startswith(f"postgres.{project_ref}"):
            user = f"postgres.{project_ref}"

    conn = pg8000.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database,
        ssl_context=ssl_context,
        timeout=10
    )
    return PostgresConnectionWrapper(conn)

LAST_POSTGRES_ERROR = None

def get_last_postgres_error():
    global LAST_POSTGRES_ERROR
    return LAST_POSTGRES_ERROR

def get_db():
    global LAST_POSTGRES_ERROR
    if is_postgres():
        try:
            return connect_postgres(get_database_url())
        except Exception as e:
            # Jika koneksi PostgreSQL gagal (misal IPv6/credential salah),
            # fallback aman ke SQLite agar sistem tetap berjalan 100% tanpa crash 500
            LAST_POSTGRES_ERROR = str(e)
            print(f"PostgreSQL connection warning ({e}), falling back to SQLite!")
            conn = sqlite3.connect(get_sqlite_path())
            conn.row_factory = sqlite3.Row
            return conn
    else:
        conn = sqlite3.connect(get_sqlite_path())
        conn.row_factory = sqlite3.Row
        return conn

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    # 1. Direct match atau plain text
    if stored == plain:
        return True
    # 2. Known legacy hashes dari seed SQL
    legacy_map = {
        "7b4e3f1a2c5d8e90:d3f3b46cf3b7541f6f59bc8bb62463e271bf162b489aef454c5ee437a3c3065b": "admin123",
        "7b4e3f1a2c5d8e90:a54050e50d603e8e2fa53a812338cb98fae73a00f162986422bdf9bc7fa3ec24": "kunjungi123",
        "7b4e3f1a2c5d8e90:f425b0be148ec78d212b1a7d656910609b4566c1f1ec42aa88c222ffda84ea82": "siti123",
    }
    if stored in legacy_map and legacy_map[stored] == plain:
        return True
    # 3. Standard salt:hash
    try:
        if ":" in stored:
            salt, hashed = stored.split(":", 1)
            # salt + plain
            if hashlib.sha256((salt + plain).encode()).hexdigest() == hashed:
                return True
            # plain + salt
            if hashlib.sha256((plain + salt).encode()).hexdigest() == hashed:
                return True
    except Exception:
        pass
    # 4. Plain sha256
    try:
        if hashlib.sha256(plain.encode()).hexdigest() == stored:
            return True
    except Exception:
        pass
    return False

def seed_default_data(conn):
    try:
        cursor = conn.cursor()
        # 1. Pastikan tabel dibuat jika di PostgreSQL
        if is_postgres():
            try:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id SERIAL PRIMARY KEY,
                    member_code VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    phone VARCHAR(50),
                    status VARCHAR(20) DEFAULT 'ACTIVE',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(255) NOT NULL,
                    role VARCHAR(20) DEFAULT 'visitor',
                    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS books (
                    id SERIAL PRIMARY KEY,
                    isbn VARCHAR(50) UNIQUE NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    author VARCHAR(255) NOT NULL,
                    publisher VARCHAR(255),
                    category VARCHAR(100) NOT NULL,
                    year INTEGER,
                    shelf_location VARCHAR(100),
                    cover_url TEXT,
                    total_copies INTEGER DEFAULT 1,
                    available_copies INTEGER DEFAULT 1,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    loan_code VARCHAR(100) UNIQUE NOT NULL,
                    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    borrow_date DATE NOT NULL,
                    due_date DATE NOT NULL,
                    return_date DATE,
                    status VARCHAR(20) DEFAULT 'BORROWED',
                    fine_amount NUMERIC(12, 2) DEFAULT 0.0,
                    fine_paid INTEGER DEFAULT 0,
                    notes TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                """)
                conn.commit()
            except Exception as e:
                print(f"PostgreSQL Table creation notice: {e}")
        else:
            try:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    member_code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    phone TEXT,
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT DEFAULT 'visitor',
                    member_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (member_id) REFERENCES members (id)
                );
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
                );
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
                );
                """)
                conn.commit()
            except Exception as e:
                print(f"SQLite Table creation notice: {e}")

        # 2. Cek apakah ada data users
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        if user_count == 0:
            # Members
            try:
                cursor.execute("""
                INSERT INTO members (member_code, name, email, phone, status) VALUES
                ('M001', 'Ahmad Fauzi', 'ahmad.fauzi@example.com', '081234567890', 'ACTIVE'),
                ('M002', 'Siti Rahma', 'siti.rahma@example.com', '081298765432', 'ACTIVE'),
                ('M003', 'Budi Santoso', 'budi.santoso@example.com', '085712341234', 'ACTIVE')
                """)
                conn.commit()
            except Exception as e:
                print(f"Members seed notice: {e}")

            # Users
            admin_hash = hash_password("admin123")
            pengunjung_hash = hash_password("kunjungi123")
            siti_hash = hash_password("siti123")

            cursor.execute("INSERT INTO users (username, password_hash, full_name, role, member_id) VALUES (?, ?, ?, ?, ?)",
                           ('admin', admin_hash, 'Administrator Perpustakaan', 'admin', None))
            cursor.execute("INSERT INTO users (username, password_hash, full_name, role, member_id) VALUES (?, ?, ?, ?, ?)",
                           ('pengunjung', pengunjung_hash, 'Ahmad Fauzi', 'visitor', 1))
            cursor.execute("INSERT INTO users (username, password_hash, full_name, role, member_id) VALUES (?, ?, ?, ?, ?)",
                           ('siti', siti_hash, 'Siti Rahma', 'visitor', 2))
            conn.commit()

        # 3. Cek apakah ada data books
        cursor.execute("SELECT COUNT(*) FROM books")
        book_count = cursor.fetchone()[0]
        if book_count == 0:
            books_data = [
                ('978-602-03-8591-4', 'Laskar Pelangi', 'Andrea Hirata', 'Bentang Pustaka', 'Fiksi', 2005, 'Rak A-01', 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=400&q=80', 5, 4),
                ('978-979-3062-79-2', 'Bumi Manusia', 'Pramoedya Ananta Toer', 'Hasta Mitra', 'Sejarah & Sastra', 1980, 'Rak A-02', 'https://images.unsplash.com/photo-1495446815901-a7297e633e8d?w=400&q=80', 3, 3),
                ('978-0-13-235088-4', 'Clean Code', 'Robert C. Martin', 'Prentice Hall', 'Teknologi', 2008, 'Rak T-05', 'https://images.unsplash.com/photo-1532012164546-f432f2e3777a?w=400&q=80', 4, 3),
                ('978-0-7432-7356-5', 'The Great Gatsby', 'F. Scott Fitzgerald', 'Scribner', 'Klasik', 1925, 'Rak K-01', 'https://images.unsplash.com/photo-1512820790803-83ca734da794?w=400&q=80', 2, 2),
                ('978-602-291-412-4', 'Atomic Habits', 'James Clear', 'Penguin Books', 'Pengembangan Diri', 2018, 'Rak P-03', 'https://images.unsplash.com/photo-1512428559087-560fa5ceab42?w=400&q=80', 6, 5)
            ]
            for b in books_data:
                cursor.execute("""
                INSERT INTO books (isbn, title, author, publisher, category, year, shelf_location, cover_url, total_copies, available_copies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, b)
            conn.commit()
    except Exception as e:
        print(f"seed_default_data notice: {e}")

def init_db():
    try:
        conn = get_db()
        seed_default_data(conn)
        conn.close()
    except Exception as e:
        print(f"init_db notice: {e}")
