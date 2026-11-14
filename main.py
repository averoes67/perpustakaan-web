from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import os
import sqlite3
import traceback
from datetime import datetime, date, timedelta
from database import get_db, init_db, verify_password, hash_password, is_postgres, seed_default_data, get_last_postgres_error

app = FastAPI(title="PustakaDigital — Sistem Informasi Perpustakaan")

# Session middleware
app.add_middleware(SessionMiddleware, secret_key="pustakadigital-secret-key-2026-xZ9q!")

# Cari folder templates di berbagai kemungkinan lokasi di Vercel / Local
def resolve_templates_dir():
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_file_dir, "templates"),
        os.path.join(current_file_dir, "api", "templates"),
        os.path.join(os.getcwd(), "templates"),
        os.path.join(os.getcwd(), "api", "templates"),
        "/var/task/templates",
        "/var/task/api/templates",
    ]
    for path in candidates:
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "home.html")):
            return path
    for path in candidates:
        if os.path.isdir(path):
            return path
    return os.path.join(current_file_dir, "templates")

TEMPLATES_DIR = resolve_templates_dir()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Global error handler agar jika ada kesalahan, traceback muncul di layar daripada Internal Server Error kosong
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_trace = traceback.format_exc()
    db_mode = "PostgreSQL (Supabase)" if is_postgres() else "SQLite"
    html_content = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <title>Sistem Perpustakaan - Error Report</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 24px; }}
            .container {{ max-width: 900px; margin: 0 auto; background: #1e293b; border-radius: 16px; padding: 32px; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
            h1 {{ color: #f87171; font-size: 20px; margin-top: 0; }}
            p {{ color: #cbd5e1; font-size: 14px; line-height: 1.6; }}
            pre {{ background: #090d16; color: #fda4af; padding: 18px; border-radius: 12px; font-size: 13px; line-height: 1.5; overflow-x: auto; border: 1px solid #e11d48; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; background: #3b82f6; color: white; margin-bottom: 12px; }}
            .hint {{ background: #1e3a5f; padding: 14px; border-radius: 8px; font-size: 13px; color: #93c5fd; margin-top: 16px; border-left: 4px solid #3b82f6; }}
        </style>
    </head>
    <body>
        <div class="container">
            <span class="badge">Mode Database: {db_mode}</span>
            <h1>Terjadi Masalah pada Server Perpustakaan</h1>
            <p>Request ke <code>{request.url.path}</code> mengalami kesalahan sistem:</p>
            <pre>{error_trace}</pre>
            <div class="hint">
                <strong>Tips Perbaikan:</strong><br>
                - Jika error menyebutkan <em>connection timeout / connection refused</em>: Periksa kembali <code>DATABASE_URL</code> di Vercel Environment Variables. Pastikan menggunakan <strong>Session/Transaction Pooler port 6543</strong> dari Supabase.<br>
                - Jika error menyebutkan <em>password authentication failed</em>: Pastikan password database di <code>DATABASE_URL</code> sudah benar.
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=500)

# Inisialisasi DB aman (tidak akan crash saat startup jika database offline)
try:
    init_db()
except Exception as e:
    print(f"Startup init_db notice: {e}")

DAILY_FINE_RATE = 2000.0

# ─── Helper ─────────────────────────────────────────────────────────────────

def get_current_user(request: Request):
    """Ambil data user dari session."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def require_admin(request: Request):
    """Return user jika admin, else None."""
    user = get_current_user(request)
    if user and user["role"] == "admin":
        return user
    return None

def parse_date(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        clean = val.split("T")[0].split(" ")[0].strip()
        try:
            return datetime.strptime(clean, "%Y-%m-%d").date()
        except Exception:
            try:
                return datetime.fromisoformat(clean).date()
            except Exception:
                return None
    return None

def update_overdue_loans(conn):
    try:
        cursor = conn.cursor()
        today = datetime.now().date()
        cursor.execute("SELECT id, due_date FROM loans WHERE status = 'BORROWED'")
        for loan in cursor.fetchall():
            due_date = parse_date(loan["due_date"])
            if due_date and today > due_date:
                days_late = (today - due_date).days
                cursor.execute(
                    "UPDATE loans SET status='OVERDUE', fine_amount=? WHERE id=?",
                    (days_late * DAILY_FINE_RATE, loan["id"])
                )
        conn.commit()
    except Exception as e:
        print(f"update_overdue_loans notice: {e}")

# ─── PUBLIK ─────────────────────────────────────────────────────────────────

# --- 0. DIAGNOSTIC / HEALTH CHECK ---
@app.get("/ping")
@app.get("/api/ping")
@app.get("/api/index/ping")
async def ping():
    db_ok = False
    db_err = None
    user_list = []
    book_count = 0
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        db_ok = bool(row)

        cursor.execute("SELECT COUNT(*) FROM users")
        uc = cursor.fetchone()[0]
        if uc == 0:
            seed_default_data(conn)

        cursor.execute("SELECT username, role FROM users")
        user_list = [f"{r[0]} ({r[1]})" for r in cursor.fetchall()]

        cursor.execute("SELECT COUNT(*) FROM books")
        book_count = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        db_err = str(e)

    return {
        "status": "ok",
        "app": "PustakaDigital",
        "database_mode": "PostgreSQL (Supabase)" if is_postgres() else "SQLite",
        "has_database_url": bool(os.environ.get("DATABASE_URL")),
        "database_connection_ok": db_ok,
        "database_error": db_err,
        "postgres_connect_error": get_last_postgres_error(),
        "users_in_database": user_list,
        "book_count": book_count,
        "templates_dir": TEMPLATES_DIR,
        "templates_found": bool(TEMPLATES_DIR and os.path.isdir(TEMPLATES_DIR))
    }

@app.get("/seed-db")
async def seed_endpoint():
    try:
        conn = get_db()
        seed_default_data(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT username, role FROM users")
        users = [f"{r[0]} ({r[1]})" for r in cursor.fetchall()]
        cursor.execute("SELECT COUNT(*) FROM books")
        bcount = cursor.fetchone()[0]
        conn.close()
        return {
            "status": "success",
            "message": "Database berhasil diinisialisasi dan di-seed dengan data default!",
            "users": users,
            "book_count": bcount
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 1. BERANDA (SUPPORT DIRECT & VERCEL SUBPATH) ---
@app.get("/", response_class=HTMLResponse)
@app.get("/api", response_class=HTMLResponse)
@app.get("/api/index.py", response_class=HTMLResponse)
async def home(request: Request):
    current_user = None
    stats = {
        "total_books": 0,
        "total_copies": 0,
        "total_members": 0,
        "total_loans": 0
    }
    recent_books = []
    db_notice = None

    try:
        current_user = get_current_user(request)
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*), COALESCE(SUM(total_copies),0) FROM books")
        row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM members WHERE status='ACTIVE'")
        total_members = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM loans")
        total_loans = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM books ORDER BY id DESC LIMIT 6")
        recent_books = cursor.fetchall()
        conn.close()

        stats = {
            "total_books": row[0] if row else 0,
            "total_copies": row[1] if row else 0,
            "total_members": total_members or 0,
            "total_loans": total_loans or 0
        }
    except Exception as e:
        db_notice = f"Catatan Database: {e}"
        print(f"Notice on home route: {e}")

    try:
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "active_page": "home",
                "current_user": current_user,
                "stats": stats,
                "recent_books": recent_books,
                "db_notice": db_notice
            }
        )
    except Exception as e:
        err_detail = traceback.format_exc()
        folder_contents = os.listdir(TEMPLATES_DIR) if os.path.exists(TEMPLATES_DIR) else 'Folder tidak ditemukan!'
        return HTMLResponse(
            content=f"""
            <div style="font-family:sans-serif;padding:30px;background:#1e293b;color:white;border-radius:10px;">
                <h2 style="color:#ef4444;">Gagal Me-render Template: {e}</h2>
                <p>Direktori Templates saat ini: <code>{TEMPLATES_DIR}</code></p>
                <p>Isi direktori: <code>{folder_contents}</code></p>
                <pre style="background:#0f172a;padding:15px;color:#fca5a5;border-radius:6px;">{err_detail}</pre>
            </div>
            """,
            status_code=500
        )

@app.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, q: str = None):
    current_user = get_current_user(request)
    conn = get_db()
    cursor = conn.cursor()
    if q and q.strip():
        s = f"%{q.strip()}%"
        cursor.execute("SELECT * FROM books WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ? OR category LIKE ? ORDER BY id DESC",
                       (s, s, s, s))
    else:
        cursor.execute("SELECT * FROM books ORDER BY id DESC")
    books = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context={"active_page": "catalog", "current_user": current_user, "books": books, "query": q}
    )

# ─── AUTH ────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, redirect: str = None):
    if get_current_user(request):
        return RedirectResponse(url=redirect if redirect else "/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None, "redirect": redirect})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    redirect: str = Form(None)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
    user = cursor.fetchone()

    # Jika user tidak ditemukan, periksa apakah database belum di-seed
    if not user:
        try:
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                seed_default_data(conn)
                cursor.execute("SELECT * FROM users WHERE username = ?", (username.strip(),))
                user = cursor.fetchone()
        except Exception:
            pass

    conn.close()

    if user and verify_password(password, user["password_hash"]):
        request.session["user_id"] = user["id"]
        # Jika ada parameter redirect target
        if redirect and redirect.startswith("/"):
            return RedirectResponse(url=redirect, status_code=303)
        # Redirect default sesuai role
        if user["role"] == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        else:
            return RedirectResponse(url="/my-loans", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Username atau password salah. Silakan coba lagi.", "redirect": redirect}
    )

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# ─── REGISTRASI ANGGOTA BARU MANDIRI ─────────────────────────────────────────

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, redirect: str = None):
    if get_current_user(request):
        return RedirectResponse(url="/my-loans", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": None, "redirect": redirect}
    )

@app.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    phone: str = Form(None),
    redirect: str = Form(None)
):
    conn = get_db()
    cursor = conn.cursor()

    def reload_reg(err):
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "error": err,
                "full_name": full_name,
                "email": email,
                "username": username,
                "phone": phone,
                "redirect": redirect
            }
        )

    # Validasi input
    if len(password) < 6:
        return reload_reg("Password minimal harus 6 karakter.")

    # Cek keunikan email & username
    cursor.execute("SELECT id FROM members WHERE email = ?", (email.strip(),))
    if cursor.fetchone():
        return reload_reg("Email tersebut sudah terdaftar sebagai anggota perpustakaan.")

    cursor.execute("SELECT id FROM users WHERE username = ?", (username.strip(),))
    if cursor.fetchone():
        return reload_reg("Username tersebut sudah digunakan. Silakan pilih username lain.")

    try:
        # Generate nomor anggota otomatis (Format M00X)
        cursor.execute("SELECT MAX(id) FROM members")
        last_id = cursor.fetchone()[0] or 0
        member_code = f"M{last_id + 1:03d}"

        # 1. Simpan ke tabel members
        cursor.execute("""
            INSERT INTO members (member_code, name, email, phone, status)
            VALUES (?, ?, ?, ?, 'ACTIVE')
        """, (member_code, full_name.strip(), email.strip(), phone.strip() if phone else None))
        new_member_id = cursor.lastrowid
        if not new_member_id:
            cursor.execute("SELECT id FROM members WHERE member_code = ?", (member_code.strip(),))
            m_row = cursor.fetchone()
            if m_row:
                new_member_id = m_row["id"]

        # 2. Simpan ke tabel users (role visitor, linked to member_id)
        pw_hash = hash_password(password)
        cursor.execute("""
            INSERT INTO users (username, password_hash, full_name, role, member_id)
            VALUES (?, ?, ?, 'visitor', ?)
        """, (username.strip(), pw_hash, full_name.strip(), new_member_id))
        new_user_id = cursor.lastrowid
        if not new_user_id:
            cursor.execute("SELECT id FROM users WHERE username = ?", (username.strip(),))
            u_row = cursor.fetchone()
            if u_row:
                new_user_id = u_row["id"]

        conn.commit()

        # Otomatis langsung login setelah pendaftaran sukses
        request.session["user_id"] = new_user_id

        # Jika ada halaman redirect target (misal sedang mau pinjam buku)
        if redirect and redirect.startswith("/"):
            return RedirectResponse(url=redirect, status_code=303)
        return RedirectResponse(url="/my-loans", status_code=303)

    except Exception as e:
        return reload_reg(f"Gagal melakukan pendaftaran: {str(e)}")
    finally:
        conn.close()

# ─── ADMIN ───────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    update_overdue_loans(conn)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(total_copies),0) FROM books")
    row = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM loans WHERE status='BORROWED'")
    active_loans = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM loans WHERE status='OVERDUE'")
    overdue_loans = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM members WHERE status='ACTIVE'")
    total_members = cursor.fetchone()[0]

    cursor.execute("""
        SELECT l.id, l.loan_code, l.borrow_date, l.due_date, l.status, l.fine_amount,
               m.name as member_name, m.member_code, b.title as book_title
        FROM loans l
        JOIN members m ON l.member_id = m.id
        JOIN books b ON l.book_id = b.id
        ORDER BY l.id DESC LIMIT 5
    """)
    recent_loans = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active_page": "dashboard",
            "current_user": current_user,
            "stats": {"total_books": row[0], "total_copies": row[1], "active_loans": active_loans,
                      "overdue_loans": overdue_loans, "total_members": total_members},
            "recent_loans": recent_loans
        }
    )

@app.get("/admin/loans", response_class=HTMLResponse)
async def admin_loans(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    update_overdue_loans(conn)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT l.*, m.name as member_name, m.member_code, m.phone as member_phone,
               b.title as book_title, b.isbn
        FROM loans l
        JOIN members m ON l.member_id = m.id
        JOIN books b ON l.book_id = b.id
        ORDER BY l.id DESC
    """)
    loans = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="loans.html",
        context={"active_page": "loans", "current_user": current_user, "loans": loans}
    )

@app.get("/admin/loans/new", response_class=HTMLResponse)
async def admin_new_loan_form(request: Request, book_id: int = None):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM books WHERE available_copies > 0 ORDER BY title ASC")
    books = cursor.fetchall()
    cursor.execute("SELECT * FROM members WHERE status='ACTIVE' ORDER BY name ASC")
    members = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="loan_form.html",
        context={"active_page": "loans_new", "current_user": current_user,
                 "books": books, "members": members, "selected_book_id": book_id, "error": None}
    )

@app.post("/admin/loans/new", response_class=HTMLResponse)
async def admin_create_loan(
    request: Request,
    member_id: int = Form(...),
    book_id: int = Form(...),
    days: int = Form(7),
    notes: str = Form(None)
):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.cursor()

    def reload_form(error_msg):
        cursor.execute("SELECT * FROM books WHERE available_copies > 0 ORDER BY title ASC")
        books = cursor.fetchall()
        cursor.execute("SELECT * FROM members WHERE status='ACTIVE' ORDER BY name ASC")
        members = cursor.fetchall()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="loan_form.html",
            context={"active_page": "loans_new", "current_user": current_user,
                     "books": books, "members": members, "selected_book_id": book_id, "error": error_msg}
        )

    # Validasi kuota
    cursor.execute("SELECT COUNT(*) FROM loans WHERE member_id=? AND status IN ('BORROWED','OVERDUE')", (member_id,))
    if cursor.fetchone()[0] >= 3:
        return reload_form("Anggota ini telah mencapai batas maksimal peminjaman (3 buku).")

    # Validasi stok buku
    cursor.execute("SELECT available_copies FROM books WHERE id=?", (book_id,))
    book = cursor.fetchone()
    if not book or book["available_copies"] <= 0:
        return reload_form("Stok buku ini sedang habis dipinjam.")

    today = datetime.now().date()
    due_date = today + timedelta(days=days)
    loan_code = f"LN-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    cursor.execute("""
        INSERT INTO loans (loan_code, member_id, book_id, borrow_date, due_date, status, notes)
        VALUES (?, ?, ?, ?, ?, 'BORROWED', ?)
    """, (loan_code, member_id, book_id, today.isoformat(), due_date.isoformat(), notes))
    cursor.execute("UPDATE books SET available_copies = available_copies - 1 WHERE id=?", (book_id,))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/admin/loans", status_code=303)

@app.post("/admin/loans/return/{loan_id}")
async def admin_return_loan(request: Request, loan_id: int):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM loans WHERE id=?", (loan_id,))
    loan = cursor.fetchone()

    if loan and loan["status"] != "RETURNED":
        today = datetime.now().date()
        due_date = parse_date(loan["due_date"])
        fine = max(0, (today - due_date).days) * DAILY_FINE_RATE if (due_date and today > due_date) else 0.0

        cursor.execute("""
            UPDATE loans SET return_date=?, status='RETURNED', fine_amount=?, fine_paid=1 WHERE id=?
        """, (today.isoformat(), fine, loan_id))
        cursor.execute("UPDATE books SET available_copies = available_copies + 1 WHERE id=?", (loan["book_id"],))
        conn.commit()

    conn.close()
    return RedirectResponse(url="/admin/loans", status_code=303)

@app.get("/admin/books/new", response_class=HTMLResponse)
async def admin_new_book_form(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="book_form.html",
        context={"active_page": "books_new", "current_user": current_user, "error": None}
    )

@app.post("/admin/books/new", response_class=HTMLResponse)
async def admin_create_book(
    request: Request,
    isbn: str = Form(...),
    title: str = Form(...),
    author: str = Form(...),
    publisher: str = Form(None),
    category: str = Form(...),
    year: int = Form(2024),
    shelf_location: str = Form(None),
    total_copies: int = Form(1),
    cover_url: str = Form(None)
):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    if not cover_url or not cover_url.strip():
        cover_url = "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=400&q=80"

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO books (isbn, title, author, publisher, category, year, shelf_location, cover_url, total_copies, available_copies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (isbn.strip(), title.strip(), author.strip(),
              publisher.strip() if publisher else None,
              category, year,
              shelf_location.strip() if shelf_location else None,
              cover_url.strip(), total_copies, total_copies))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="book_form.html",
            context={"active_page": "books_new", "current_user": current_user,
                     "error": f"ISBN '{isbn}' sudah terdaftar dalam sistem."}
        )
    conn.close()
    return RedirectResponse(url="/catalog", status_code=303)


# ─── VISITOR: PINJAMAN SAYA ──────────────────────────────────────────────────

@app.get("/my-loans", response_class=HTMLResponse)
async def my_loans(request: Request):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if current_user["role"] != "visitor" or not current_user["member_id"]:
        return RedirectResponse(url="/", status_code=303)

    conn = get_db()
    update_overdue_loans(conn)
    cursor = conn.cursor()

    # Data anggota
    cursor.execute("SELECT * FROM members WHERE id=?", (current_user["member_id"],))
    member = cursor.fetchone()

    # Semua pinjaman anggota ini
    cursor.execute("""
        SELECT l.*, b.title as book_title
        FROM loans l
        JOIN books b ON l.book_id = b.id
        WHERE l.member_id = ?
        ORDER BY l.id DESC
    """, (current_user["member_id"],))
    loans = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM loans WHERE member_id=? AND status IN ('BORROWED','OVERDUE')", (current_user["member_id"],))
    active_count = cursor.fetchone()[0]
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="my_loans.html",
        context={
            "active_page": "my_loans",
            "current_user": current_user,
            "member": member,
            "loans": loans,
            "active_count": active_count,
            "success_msg": request.session.pop("success_msg", None)
        }
    )

@app.post("/my-loans/return/{loan_id}")
async def visitor_return_loan(request: Request, loan_id: int):
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "visitor" or not current_user["member_id"]:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.cursor()
    # Pastikan loan ini milik anggota yang login
    cursor.execute("SELECT * FROM loans WHERE id=? AND member_id=?", (loan_id, current_user["member_id"]))
    loan = cursor.fetchone()

    if loan and loan["status"] != "RETURNED":
        today = datetime.now().date()
        due_date = parse_date(loan["due_date"])
        fine = max(0, (today - due_date).days) * DAILY_FINE_RATE if (due_date and today > due_date) else 0.0

        cursor.execute("""
            UPDATE loans SET return_date=?, status='RETURNED', fine_amount=?, fine_paid=1 WHERE id=?
        """, (today.isoformat(), fine, loan_id))
        cursor.execute("UPDATE books SET available_copies = available_copies + 1 WHERE id=?", (loan["book_id"],))
        conn.commit()

    conn.close()
    return RedirectResponse(url="/my-loans", status_code=303)


# ─── VISITOR: PINJAM BUKU ────────────────────────────────────────────────────

@app.get("/borrow", response_class=HTMLResponse)
async def borrow_page(request: Request, book_id: int = None):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    if current_user["role"] != "visitor" or not current_user["member_id"]:
        # Admin diarahkan ke form admin
        return RedirectResponse(url="/admin/loans/new", status_code=303)

    conn = get_db()
    update_overdue_loans(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM loans WHERE member_id=? AND status IN ('BORROWED','OVERDUE')", (current_user["member_id"],))
    active_count = cursor.fetchone()[0]

    cursor.execute("SELECT * FROM books WHERE available_copies > 0 ORDER BY title ASC")
    books = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="borrow.html",
        context={
            "active_page": "borrow",
            "current_user": current_user,
            "books": books,
            "active_count": active_count,
            "selected_book_id": book_id,
            "error": None
        }
    )

@app.post("/borrow", response_class=HTMLResponse)
async def borrow_submit(
    request: Request,
    book_id: int = Form(...),
    days: int = Form(7)
):
    current_user = get_current_user(request)
    if not current_user or current_user["role"] != "visitor" or not current_user["member_id"]:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    update_overdue_loans(conn)
    cursor = conn.cursor()

    def reload_borrow(error_msg):
        cursor.execute("SELECT COUNT(*) FROM loans WHERE member_id=? AND status IN ('BORROWED','OVERDUE')", (current_user["member_id"],))
        active_count = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM books WHERE available_copies > 0 ORDER BY title ASC")
        books = cursor.fetchall()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="borrow.html",
            context={"active_page": "borrow", "current_user": current_user,
                     "books": books, "active_count": active_count,
                     "selected_book_id": book_id, "error": error_msg}
        )

    # Validasi kuota
    cursor.execute("SELECT COUNT(*) FROM loans WHERE member_id=? AND status IN ('BORROWED','OVERDUE')", (current_user["member_id"],))
    if cursor.fetchone()[0] >= 3:
        return reload_borrow("Kuota pinjam Anda penuh (maksimal 3 buku). Kembalikan buku terlebih dahulu.")

    # Validasi stok
    cursor.execute("SELECT available_copies FROM books WHERE id=?", (book_id,))
    book = cursor.fetchone()
    if not book or book["available_copies"] <= 0:
        return reload_borrow("Stok buku ini sedang habis dipinjam oleh anggota lain.")

    today = datetime.now().date()
    due_date = today + timedelta(days=days)
    loan_code = f"LN-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    cursor.execute("""
        INSERT INTO loans (loan_code, member_id, book_id, borrow_date, due_date, status)
        VALUES (?, ?, ?, ?, ?, 'BORROWED')
    """, (loan_code, current_user["member_id"], book_id, today.isoformat(), due_date.isoformat()))
    cursor.execute("UPDATE books SET available_copies = available_copies - 1 WHERE id=?", (book_id,))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/my-loans", status_code=303)


# ─── ADMIN: MANAJEMEN ANGGOTA ────────────────────────────────────────────────

@app.get("/admin/members", response_class=HTMLResponse)
async def admin_members(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.cursor()
    # Join dengan users untuk tampilkan username, dan hitung pinjaman aktif
    cursor.execute("""
        SELECT m.*,
               u.username,
               (SELECT COUNT(*) FROM loans l WHERE l.member_id = m.id AND l.status IN ('BORROWED','OVERDUE')) as active_loans
        FROM members m
        LEFT JOIN users u ON u.member_id = m.id
        ORDER BY m.id ASC
    """)
    members = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="members.html",
        context={"active_page": "members", "current_user": current_user, "members": members}
    )

@app.get("/admin/members/new", response_class=HTMLResponse)
async def admin_new_member_form(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="member_form.html",
        context={"active_page": "members_new", "current_user": current_user, "error": None}
    )

@app.post("/admin/members/new", response_class=HTMLResponse)
async def admin_create_member(
    request: Request,
    member_code: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None),
    status: str = Form("ACTIVE"),
    create_account: str = Form(None),
    username: str = Form(None),
    password: str = Form(None)
):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    conn = get_db()
    cursor = conn.cursor()

    def reload_form(error_msg):
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="member_form.html",
            context={
                "active_page": "members_new", "current_user": current_user,
                "error": error_msg,
                "member_code": member_code, "name": name, "email": email,
                "phone": phone, "username": username
            }
        )

    # Validasi duplikat member_code dan email
    cursor.execute("SELECT id FROM members WHERE member_code=? OR email=?", (member_code.strip(), email.strip()))
    if cursor.fetchone():
        return reload_form("Nomor anggota atau email sudah terdaftar di sistem.")

    # Jika buat akun login, validasi dulu
    if create_account:
        if not username or not username.strip():
            return reload_form("Username harus diisi jika ingin membuat akun login.")
        if not password or len(password) < 6:
            return reload_form("Password minimal 6 karakter.")
        cursor.execute("SELECT id FROM users WHERE username=?", (username.strip(),))
        if cursor.fetchone():
            return reload_form(f"Username '{username}' sudah digunakan oleh akun lain.")

    try:
        # Simpan anggota baru
        cursor.execute("""
            INSERT INTO members (member_code, name, email, phone, status)
            VALUES (?, ?, ?, ?, ?)
        """, (member_code.strip(), name.strip(), email.strip(),
              phone.strip() if phone else None, status))
        new_member_id = cursor.lastrowid
        if not new_member_id:
            cursor.execute("SELECT id FROM members WHERE member_code = ?", (member_code.strip(),))
            m_row = cursor.fetchone()
            if m_row:
                new_member_id = m_row["id"]

        # Buat akun user jika diminta
        if create_account and username and password:
            pw_hash = hash_password(password)
            cursor.execute("""
                INSERT INTO users (username, password_hash, full_name, role, member_id)
                VALUES (?, ?, ?, 'visitor', ?)
            """, (username.strip(), pw_hash, name.strip(), new_member_id))

        conn.commit()
    except sqlite3.IntegrityError as e:
        return reload_form(f"Gagal menyimpan: {str(e)}")
    finally:
        conn.close()

    return RedirectResponse(url="/admin/members", status_code=303)
