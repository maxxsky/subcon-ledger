"""
Subcon Payment Monitor — Configuration Example
Copy file ini ke config.py lalu isi nilai asli:
    cp config.example.py config.py
JANGAN pernah commit config.py (sudah di .gitignore) karena berisi password.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── APP ──────────────────────────────────────────────────────
SECRET_KEY = "ganti-ini-dengan-random-string-panjang"
PORT = 3463
DEBUG = False

# ── AUTH (hardcoded users) ───────────────────────────────────
# role: "admin" (bisa input/upload/delete) atau "viewer" (read-only)
USERS = {
    "admin": {"password": "ganti-password-admin", "role": "admin", "name": "Administrator"},
    "viewer": {"password": "ganti-password-viewer", "role": "viewer", "name": "Viewer"},
}

# ── DATABASE ─────────────────────────────────────────────────
DB_PATH = os.path.join(BASE_DIR, "data", "subcon.db")

# ── UPLOAD ───────────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"xlsx"}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max

# ── BACKUP ───────────────────────────────────────────────────
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
BACKUP_KEEP_DAYS = 30

# ── SERTIFIKAT PARSER — Cell Coordinates ─────────────────────
SERTIFIKAT_CELLS = {
    "header_check":     (2, 2),    # Cell yang mengandung kata "SERTIFIKAT"
    "subcon_name":      (7, 6),    # Nama subkontraktor
    "payment_number":   (7, 14),   # Nomor pembayaran, e.g. "1 (Satu)"
    "work_desc":        (8, 6),    # Deskripsi pekerjaan
    "date":             (8, 14),   # Tanggal pembayaran
    "spk_number":       (9, 6),    # Nomor SPK
    "contract_value":   (21, 12),  # Nilai kontrak akhir (Nilai SPK Akhir)
    "contract_value_alt": (16, 12),# Fallback: Nilai SPK Awal
    "contract_initial": (16, 12),  # Nilai SPK Awal (sebelum perubahan)
    "variation_add":    (18, 9),   # a. Penambahan SPK
    "variation_reduce": (19, 9),   # b. Pengurangan SPK
    "dp_amount":        (23, 9),   # Uang Muka / DP
    "retention_pct":    (24, 3),   # Persentase garansi/retensi
    "net_payment":      (44, 14),  # Fallback — prefer dynamic scan by label
    "total_invoice":    (46, 14),  # Fallback — prefer dynamic scan by label
    "cumulative_progress": (32, 7),  # Fallback — prefer dynamic scan by label
}

# Sheet name prefix yang dianggap sebagai SP sheet
SP_SHEET_PREFIX = "SP"

# ── BUSINESS RULES ───────────────────────────────────────────
DEFAULT_RETENTION_PCT = 0.0       # % retensi default jika tidak ada di sertifikat
LUNAS_THRESHOLD = 100.0           # % vs payable untuk dianggap lunas
OVERBILLING_THRESHOLD = 100.0     # % di atas ini dianggap over-billing
RETENTION_ALERT_DAYS = 30         # Alert retensi jatuh tempo dalam X hari ke depan
