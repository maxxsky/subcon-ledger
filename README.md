# Subcon Payment Monitor

Web app monitoring pembayaran subkontraktor. Multi-user, browser-based, dengan audit trail.

## Tech Stack
- **Backend:** Flask + SQLAlchemy + SQLite
- **Frontend:** Bootstrap 5 + Chart.js (no build step)
- **Auth:** Hardcoded users di `config.py`

## Quick Start (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Siapkan config
cp config.example.py config.py
#    → isi SECRET_KEY & password user di config.py

# 3. Jalankan
python app.py

# 4. Buka browser
http://localhost:3463
```

> **Penting:** `config.py` berisi password asli dan sudah di-`.gitignore`.
> Jangan pernah commit file ini ke repo.

Users diatur lewat dict `USERS` di `config.py`:
| Key | Role |
|---|---|
| admin | Admin (input/upload/delete) |
| viewer | Viewer (read-only) |

## Deploy ke VPS (Ubuntu 24.04)

```bash
# Install
pip install -r requirements.txt gunicorn

# Jalankan dengan gunicorn
gunicorn -w 2 -b 0.0.0.0:3463 app:app

# Atau pakai systemd service:
# sudo nano /etc/systemd/system/subcon-monitor.service
```

Contoh systemd service:
```ini
[Unit]
Description=Subcon Payment Monitor
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/subcon-monitor
ExecStart=gunicorn -w 2 -b 0.0.0.0:3463 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

## Konfigurasi Cell Sertifikat

Edit `config.py` → `SERTIFIKAT_CELLS`. Ubah koordinat `net_payment` jika posisinya berbeda:

```python
SERTIFIKAT_CELLS = {
    "net_payment": (44, 14),  # ← ubah row/col sesuai format sertifikatmu
    ...
}
```

## Alur Upload Sertifikat

1. Upload file `.xlsx`
2. Sistem parse otomatis, cari match by SPK number
3. **Preview halaman** → review setiap pembayaran
4. Pilih subkon & WP secara manual jika tidak auto-match
5. Centang item yang mau disimpan → Konfirmasi
6. Data tersimpan + tercatat di audit log

Tidak ada payment yang tersimpan tanpa konfirmasi eksplisit dari user.

## Backup

- Manual: klik **💾 Backup** di navbar
- Otomatis: tambahkan cron job di VPS:

```bash
# Backup setiap hari jam 02:00
0 2 * * * cp /path/to/subcon-monitor/data/subcon.db /path/to/subcon-monitor/backups/subcon_$(date +\%Y\%m\%d).db
```

## Struktur Folder

```
subcon-monitor/
├── app.py              # Flask app + routes
├── models.py           # SQLAlchemy models
├── config.py           # Konfigurasi (users, cell coordinates, dll)
├── parsers/
│   └── sertifikat.py   # Parser sertifikat .xlsx
├── exports/
│   └── excel.py        # Generate Excel monitoring
├── templates/          # Jinja2 HTML templates
├── uploads/            # File sertifikat yang diupload
├── data/
│   └── subcon.db       # SQLite database
├── backups/            # Backup database
└── requirements.txt
```
