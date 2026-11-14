@echo off
setlocal
echo ===========================================
echo       AUTO PUSH KE GITHUB & VERCEL
echo ===========================================
echo.

set /p MSG="Masukkan pesan commit (tekan Enter untuk default 'Update web perpustakaan'): "
if "%MSG%"=="" set MSG=Update web perpustakaan

echo.
echo [1/3] Menambahkan file yang berubah...
git add .

echo [2/3] Menyimpan commit: "%MSG%"...
git commit -m "%MSG%"

echo [3/3] Mengirim (push) ke GitHub...
git push origin main

echo.
if %ERRORLEVEL% EQU 0 (
    echo ===========================================
    echo  BERHASIL! Vercel akan otomatis redeploy!
    echo ===========================================
) else (
    echo ===========================================
    echo  TERJADI KESALAHAN SAAT PUSH!
    echo  Pastikan remote GitHub sudah terhubung.
    echo ===========================================
)
pause
