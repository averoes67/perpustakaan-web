param (
    [string]$msg = "Update web perpustakaan"
)

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "      AUTO PUSH KE GITHUB & VERCEL         " -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Menambahkan file yang berubah..." -ForegroundColor Yellow
git add .

Write-Host "[2/3] Menyimpan commit: '$msg'..." -ForegroundColor Yellow
git commit -m "$msg"

Write-Host "[3/3] Mengirim (push) ke GitHub..." -ForegroundColor Yellow
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n===========================================" -ForegroundColor Green
    Write-Host " BERHASIL! Vercel akan otomatis redeploy!   " -ForegroundColor Green
    Write-Host "===========================================" -ForegroundColor Green
} else {
    Write-Host "`n===========================================" -ForegroundColor Red
    Write-Host " TERJADI KESALAHAN SAAT PUSH!              " -ForegroundColor Red
    Write-Host " Pastikan remote GitHub sudah terhubung.    " -ForegroundColor Red
    Write-Host "===========================================" -ForegroundColor Red
}
