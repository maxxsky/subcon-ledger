"""
Migrasi Fase 1 — Subcon Ledger skema lama → baru.

Satu kali jalan (one-off), bukan Alembic. Sebelum jalan:
1. BACKUP dulu — skrip ini otomatis menyalin DB ke /root/subcon_migration_backup_fase1.db
   (di luar direktori proyek)
2. Baseline COUNT/SUM payments dicatat oleh skrip dan diverifikasi setelahnya

Perubahan skema:
- projects       → tabel BARU + 1 proyek default
- subcons        → RENAME vendors + kolom baru (jenis/kontak/wilayah/npwp/aktif)
- spks           → REBUILD: subcon_id→vendor_id, + project_id & kolom fase berikutnya
- certificates   → tabel BARU, dibuat dari payments lama
- payments       → REBUILD: date String→Date, -description/-payment_number/-source,
                  + certificate_id nullable

Verifikasi otomatis di akhir:
- COUNT(payments) sebelum == sesudah
- SUM(payments.amount) sebelum == sesudah
- SUM(certificates.nilai_tersertifikasi) == SUM(payments.amount non-DP)
"""

import datetime
import os
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "subcon.db")
BACKUP_PATH = "/root/subcon_migration_backup_fase1.db"


def log(msg):
    print(f"[migrasi] {msg}")


def main():
    if not os.path.exists(DB_PATH):
        log(f"DB tidak ditemukan: {DB_PATH}")
        sys.exit(1)

    # ── 1. BACKUP di luar proyek ──
    shutil.copy2(DB_PATH, BACKUP_PATH)
    log(f"Backup → {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Cek sudah pernah migrasi (guard idempotent)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vendors'")
    if cur.fetchone():
        log("ABORT: tabel vendors sudah ada — migrasi sudah pernah dijalankan.")
        sys.exit(1)

    # ── Baseline ──
    base_count = cur.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    base_sum = cur.execute("SELECT ROUND(SUM(amount),2) FROM payments").fetchone()[0]
    log(f"Baseline payments: count={base_count}, sum={base_sum}")

    # ── 2. projects ──
    cur.execute("""CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        nama VARCHAR(200) NOT NULL,
        lokasi VARCHAR(200),
        nilai_kontrak FLOAT,
        margin_tender_pct FLOAT,
        tanggal_mulai DATE,
        durasi_rencana_bulan INTEGER,
        status VARCHAR(50),
        created_at DATETIME
    )""")
    cur.execute(
        "INSERT INTO projects (nama, status, created_at) VALUES (?, ?, ?)",
        ("Proyek Default", "aktif", datetime.datetime.utcnow()),
    )
    default_project_id = cur.lastrowid
    log(f"projects: proyek default id={default_project_id}")

    # ── 3. subcons → vendors ──
    cur.execute("ALTER TABLE subcons RENAME TO vendors")
    cur.execute("ALTER TABLE vendors ADD COLUMN jenis VARCHAR(20) DEFAULT 'subkon'")
    cur.execute("ALTER TABLE vendors ADD COLUMN kontak VARCHAR(100)")
    cur.execute("ALTER TABLE vendors ADD COLUMN wilayah VARCHAR(100)")
    cur.execute("ALTER TABLE vendors ADD COLUMN npwp VARCHAR(50)")
    cur.execute("ALTER TABLE vendors ADD COLUMN aktif BOOLEAN DEFAULT 1")
    cur.execute("UPDATE vendors SET jenis='subkon'")
    vcount = cur.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    log(f"vendors: {vcount} baris (semua jenis=subkon)")

    # ── 4. spks rebuild ──
    cur.execute("""CREATE TABLE spks_new (
        id INTEGER PRIMARY KEY,
        vendor_id INTEGER NOT NULL REFERENCES vendors(id),
        project_id INTEGER NOT NULL REFERENCES projects(id),
        rap_item_id INTEGER,
        procurement_request_id INTEGER,
        prelim_item_id INTEGER,
        variation_id INTEGER,
        jenis VARCHAR(10) DEFAULT 'SPK',
        tanggal_terbit DATE,
        status VARCHAR(20) DEFAULT 'aktif',
        alokasi_biaya VARCHAR(20) DEFAULT 'rap_item',
        spk_number VARCHAR(200),
        work_description VARCHAR(500),
        contract_value FLOAT,
        retention_pct FLOAT,
        retention_release_date DATE,
        total_additions FLOAT,
        total_reductions FLOAT,
        created_at DATETIME
    )""")
    cur.execute(
        """INSERT INTO spks_new
           (id, vendor_id, project_id, jenis, alokasi_biaya, spk_number,
            work_description, contract_value, retention_pct,
            retention_release_date, total_additions, total_reductions, created_at)
           SELECT id, subcon_id, ?, 'SPK', 'rap_item', spk_number,
            work_description, contract_value, retention_pct,
            retention_release_date, total_additions, total_reductions, created_at
           FROM spks""",
        (default_project_id,),
    )
    cur.execute("DROP TABLE spks")
    cur.execute("ALTER TABLE spks_new RENAME TO spks")
    scount = cur.execute("SELECT COUNT(*) FROM spks").fetchone()[0]
    log(f"spks: rebuild {scount} baris (subcon_id→vendor_id, project_id={default_project_id})")

    # ── 5. certificates + 6. payments rebuild ──
    cur.execute("""CREATE TABLE certificates (
        id INTEGER PRIMARY KEY,
        spk_id INTEGER NOT NULL REFERENCES spks(id),
        nomor VARCHAR(100),
        periode VARCHAR(10),
        tanggal DATE,
        nilai_tersertifikasi FLOAT,
        progress_factor FLOAT,
        sertifikat_file VARCHAR(300),
        source VARCHAR(20),
        created_by VARCHAR(50),
        created_at DATETIME
    )""")
    cur.execute("""CREATE TABLE payments_new (
        id INTEGER PRIMARY KEY,
        spk_id INTEGER NOT NULL REFERENCES spks(id),
        certificate_id INTEGER REFERENCES certificates(id),
        amount FLOAT NOT NULL,
        date DATE,
        is_dp BOOLEAN,
        created_by VARCHAR(50),
        created_at DATETIME
    )""")

    old_payments = cur.execute(
        """SELECT id, spk_id, description, amount, date, payment_number, is_dp,
                  source, sertifikat_file, progress_factor, created_by, created_at
           FROM payments ORDER BY id"""
    ).fetchall()

    cert_count = 0
    dp_count = 0
    for p in old_payments:
        (pid, spk_id, _desc, amount, date_str, payment_number,
         is_dp, source, sfile, pf, created_by, created_at) = (
            p["id"], p["spk_id"], p["description"], p["amount"], p["date"],
            p["payment_number"], p["is_dp"], p["source"], p["sertifikat_file"],
            p["progress_factor"], p["created_by"], p["created_at"])
        date_val = date_str[:10] if date_str else None
        periode = date_str[:7] if date_str and len(date_str) >= 7 else None

        if is_dp:
            # DP → Payment tanpa certificate
            cert_id = None
            dp_count += 1
        else:
            cur.execute(
                """INSERT INTO certificates
                   (spk_id, nomor, periode, tanggal, nilai_tersertifikasi,
                    progress_factor, sertifikat_file, source, created_by, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (spk_id,
                 str(payment_number) if payment_number is not None else "",
                 periode, date_val, amount, pf, sfile,
                 source or "manual", created_by, created_at),
            )
            cert_id = cur.lastrowid
            cert_count += 1

        cur.execute(
            """INSERT INTO payments_new
               (id, spk_id, certificate_id, amount, date, is_dp, created_by, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (pid, spk_id, cert_id, amount, date_val, is_dp, created_by, created_at),
        )

    cur.execute("DROP TABLE payments")
    cur.execute("ALTER TABLE payments_new RENAME TO payments")
    log(f"certificates: {cert_count} dibuat; DP tanpa cert: {dp_count}")

    conn.commit()

    # ── 7. Verifikasi ──
    after_count = cur.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    after_sum = cur.execute("SELECT ROUND(SUM(amount),2) FROM payments").fetchone()[0]
    cert_sum = cur.execute(
        "SELECT ROUND(SUM(nilai_tersertifikasi),2) FROM certificates"
    ).fetchone()[0]
    nondp_sum = cur.execute(
        "SELECT ROUND(SUM(amount),2) FROM payments WHERE is_dp=0 OR is_dp IS NULL"
    ).fetchone()[0]

    log("── Verifikasi ──")
    log(f"COUNT payments: {base_count} → {after_count} {'✅' if base_count == after_count else '❌ MISMATCH'}")
    log(f"SUM payments: {base_sum} → {after_sum} {'✅' if abs(base_sum - after_sum) < 0.01 else '❌ MISMATCH'}")
    log(f"SUM certificates.nilai_tersertifikasi: {cert_sum} vs SUM payments non-DP: {nondp_sum} "
        f"{'✅' if abs(cert_sum - nondp_sum) < 0.01 else '❌ MISMATCH'}")

    ok = (base_count == after_count
          and abs(base_sum - after_sum) < 0.01
          and abs(cert_sum - nondp_sum) < 0.01)
    if not ok:
        log("❌ VERIFIKASI GAGAL — RESTORE backup: "
            f"cp {BACKUP_PATH} {DB_PATH}")
        sys.exit(1)

    log("✅ Semua verifikasi lulus. Migrasi selesai.")
    conn.close()


if __name__ == "__main__":
    main()
