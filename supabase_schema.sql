-- 1. TABEL ANGGOTA (MEMBERS)
CREATE TABLE IF NOT EXISTS members (
    id SERIAL PRIMARY KEY,
    member_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    status VARCHAR(20) DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. TABEL USERS (LOGIN ADMIN & PENGUNJUNG)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'visitor', -- 'admin' atau 'visitor'
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. TABEL BUKU (BOOKS)
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

-- 4. TABEL PEMINJAMAN (LOANS)
CREATE TABLE IF NOT EXISTS loans (
    id SERIAL PRIMARY KEY,
    loan_code VARCHAR(100) UNIQUE NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    borrow_date DATE NOT NULL,
    due_date DATE NOT NULL,
    return_date DATE,
    status VARCHAR(20) DEFAULT 'BORROWED', -- 'BORROWED', 'RETURNED', 'OVERDUE'
    fine_amount NUMERIC(12, 2) DEFAULT 0.0,
    fine_paid INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- SEED DATA AWAL ANGGOTA
INSERT INTO members (member_code, name, email, phone, status) VALUES
('M001', 'Ahmad Fauzi', 'ahmad.fauzi@example.com', '081234567890', 'ACTIVE'),
('M002', 'Siti Rahma', 'siti.rahma@example.com', '081298765432', 'ACTIVE'),
('M003', 'Budi Santoso', 'budi.santoso@example.com', '085712341234', 'ACTIVE')
ON CONFLICT (member_code) DO NOTHING;

-- SEED DATA AWAL USERS (password hash sha256 + salt standar perpustakaan)
-- admin: admin123 | pengunjung: kunjungi123 | siti: siti123
INSERT INTO users (username, password_hash, full_name, role, member_id) VALUES
('admin', '7b4e3f1a2c5d8e90:d3f3b46cf3b7541f6f59bc8bb62463e271bf162b489aef454c5ee437a3c3065b', 'Administrator Perpustakaan', 'admin', NULL),
('pengunjung', '7b4e3f1a2c5d8e90:a54050e50d603e8e2fa53a812338cb98fae73a00f162986422bdf9bc7fa3ec24', 'Ahmad Fauzi', 'visitor', 1),
('siti', '7b4e3f1a2c5d8e90:f425b0be148ec78d212b1a7d656910609b4566c1f1ec42aa88c222ffda84ea82', 'Siti Rahma', 'visitor', 2)
ON CONFLICT (username) DO NOTHING;

-- SEED DATA AWAL BUKU
INSERT INTO books (isbn, title, author, publisher, category, year, shelf_location, cover_url, total_copies, available_copies) VALUES
('978-602-03-8591-4', 'Laskar Pelangi', 'Andrea Hirata', 'Bentang Pustaka', 'Fiksi', 2005, 'Rak A-01', 'https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=400&q=80', 5, 4),
('978-979-3062-79-2', 'Bumi Manusia', 'Pramoedya Ananta Toer', 'Hasta Mitra', 'Sejarah & Sastra', 1980, 'Rak A-02', 'https://images.unsplash.com/photo-1495446815901-a7297e633e8d?w=400&q=80', 3, 3),
('978-0-13-235088-4', 'Clean Code', 'Robert C. Martin', 'Prentice Hall', 'Teknologi', 2008, 'Rak T-05', 'https://images.unsplash.com/photo-1532012164546-f432f2e3777a?w=400&q=80', 4, 3),
('978-0-7432-7356-5', 'The Great Gatsby', 'F. Scott Fitzgerald', 'Scribner', 'Klasik', 1925, 'Rak K-01', 'https://images.unsplash.com/photo-1512820790803-83ca734da794?w=400&q=80', 2, 2),
('978-602-291-412-4', 'Atomic Habits', 'James Clear', 'Penguin Books', 'Pengembangan Diri', 2018, 'Rak P-03', 'https://images.unsplash.com/photo-1512428559087-560fa5ceab42?w=400&q=80', 6, 5)
ON CONFLICT (isbn) DO NOTHING;

