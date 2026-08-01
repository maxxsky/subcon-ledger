"""
Models — SQLAlchemy ORM untuk Subcon Ledger.
Struktur: Project → Vendor → SPK/PO → Certificate → Payment
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Vendor(db.Model):
    """Vendor global lintas proyek — subkon atau supplier (Fase 6: riwayat vendor)."""
    __tablename__ = "vendors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    jenis = db.Column(db.String(20), default="subkon")   # "subkon" | "supplier"
    kontak = db.Column(db.String(100), nullable=True)
    wilayah = db.Column(db.String(100), nullable=True)
    npwp = db.Column(db.String(50), nullable=True)
    aktif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    spks = db.relationship("SPK", backref="vendor",
                           cascade="all, delete-orphan", lazy=True)

    # ── Angka turunan — basis KONSISTEN: total_final_contract (B1) ──
    @property
    def total_contract(self):
        return sum(spk.contract_value for spk in self.spks)

    @property
    def total_final_contract(self):
        return sum(spk.final_contract for spk in self.spks)

    @property
    def total_paid(self):
        return sum(spk.total_paid for spk in self.spks)

    @property
    def total_retention(self):
        return sum(spk.retention_amount for spk in self.spks)

    @property
    def retention_remaining(self):
        return sum(spk.retention_remaining for spk in self.spks)

    @property
    def payable(self):
        return self.total_final_contract - self.total_retention

    @property
    def pct_vs_contract(self):
        if self.total_final_contract <= 0:
            return 0.0
        return round(self.total_paid / self.total_final_contract * 100, 2)

    @property
    def pct_vs_payable(self):
        if self.payable <= 0:
            return 0.0
        return round(self.total_paid / self.payable * 100, 2)

    @property
    def is_lunas(self):
        from config import LUNAS_THRESHOLD
        return self.pct_vs_payable >= LUNAS_THRESHOLD

    @property
    def is_overbilling(self):
        from config import OVERBILLING_THRESHOLD
        return self.pct_vs_contract > OVERBILLING_THRESHOLD

    @property
    def segments(self):
        c = self.total_final_contract
        if c <= 0:
            return {"paid_pct": 0, "remaining_pct": 0, "retention_pct": 0, "overbill": False}
        paid = self.total_paid
        ret = self.retention_remaining
        overbill = paid > (c - ret) + 1
        if overbill:
            return {"paid_pct": 100, "remaining_pct": 0, "retention_pct": 0, "overbill": True}
        paid_pct = min(paid / c * 100, 100)
        ret_pct = min(ret / c * 100, max(0.0, 100 - paid_pct))
        remaining_pct = max(0.0, 100 - paid_pct - ret_pct)
        return {
            "paid_pct": round(paid_pct, 2),
            "remaining_pct": round(remaining_pct, 2),
            "retention_pct": round(ret_pct, 2),
            "overbill": overbill,
        }

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "jenis": self.jenis,
            "kontak": self.kontak,
            "wilayah": self.wilayah,
            "npwp": self.npwp,
            "aktif": self.aktif,
            "total_contract": self.total_contract,
            "total_final_contract": self.total_final_contract,
            "total_paid": self.total_paid,
            "total_retention": self.total_retention,
            "payable": self.payable,
            "sisa": max(self.total_final_contract - self.total_paid, 0),
            "pct_vs_contract": self.pct_vs_contract,
            "pct_vs_payable": self.pct_vs_payable,
            "is_lunas": self.is_lunas,
            "is_overbilling": self.is_overbilling,
        }


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(200), nullable=False)
    lokasi = db.Column(db.String(200), nullable=True)
    nilai_kontrak = db.Column(db.Float, default=0.0)
    margin_tender_pct = db.Column(db.Float, nullable=True)
    tanggal_mulai = db.Column(db.Date, nullable=True)
    durasi_rencana_bulan = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(50), default="aktif")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    spks = db.relationship("SPK", backref="project", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "nama": self.nama,
            "lokasi": self.lokasi,
            "nilai_kontrak": self.nilai_kontrak,
            "margin_tender_pct": self.margin_tender_pct,
            "status": self.status,
        }


class SPK(db.Model):
    __tablename__ = "spks"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    # Kolom FK fase berikutnya — int nullable sekarang, constraint ditambah saat tabel tujuan ada
    rap_item_id = db.Column(db.Integer, nullable=True)            # FK Fase 2
    procurement_request_id = db.Column(db.Integer, nullable=True)  # FK Fase 3
    prelim_item_id = db.Column(db.Integer, nullable=True)          # FK Fase 2
    variation_id = db.Column(db.Integer, nullable=True)            # FK Fase 3
    jenis = db.Column(db.String(10), default="SPK")                # "SPK" | "PO"
    tanggal_terbit = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="aktif")
    # alokasi_biaya wajib diisi di level aplikasi, tanpa opsi "lain-lain"
    alokasi_biaya = db.Column(db.String(20), default="rap_item")   # rap_item|prelim|variation|rework|proyek_lain

    spk_number = db.Column(db.String(200), default="")
    work_description = db.Column(db.String(500), default="")
    contract_value = db.Column(db.Float, default=0.0)
    retention_pct = db.Column(db.Float, default=0.0)
    retention_release_date = db.Column(db.Date, nullable=True)
    total_additions = db.Column(db.Float, default=0.0)
    total_reductions = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    certificates = db.relationship("Certificate", backref="spk",
                                   cascade="all, delete-orphan", lazy=True)
    payments = db.relationship("Payment", backref="spk",
                               cascade="all, delete-orphan", lazy=True)

    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments)

    @property
    def retention_amount(self):
        if self.retention_pct > 0:
            return self.final_contract * self.retention_pct / 100
        return 0.0

    @property
    def final_contract(self):
        return self.contract_value + self.total_additions - self.total_reductions

    @property
    def retention_remaining(self):
        released = max(self.total_paid - self.payable, 0)
        return max(self.retention_amount - released, 0.0)

    @property
    def retention_release_info(self):
        if self.retention_remaining > 0 or not self.payments:
            return None
        for p in reversed(self.payments):
            if abs(p.amount - self.retention_amount) < max(self.retention_amount * 0.01, 1000):
                return {"date": p.date, "amount": p.amount}
        return {"date": "✅ Lunas", "amount": 0}

    @property
    def retention_due_date(self):
        """Tanggal jatuh tempo retensi: 1 tahun setelah sertifikat progress 100%."""
        from datetime import timedelta
        pct_100 = None
        for c in sorted(self.certificates, key=lambda x: x.id):
            if c.progress_factor and c.progress_factor >= 0.995:
                pct_100 = c
                break
        if not pct_100 or not pct_100.tanggal:
            return None
        try:
            return (pct_100.tanggal + timedelta(days=365)).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return None

    @property
    def payable(self):
        return self.final_contract - self.retention_amount

    @property
    def sisa_bayar(self):
        return max(self.final_contract - self.total_paid - self.retention_amount, 0)

    @property
    def pct_vs_contract(self):
        if self.final_contract <= 0:
            return 0.0
        return round(self.total_paid / self.final_contract * 100, 2)

    @property
    def pct_vs_payable(self):
        if self.payable <= 0:
            return 0.0
        return round(self.total_paid / self.payable * 100, 2)

    @property
    def is_lunas(self):
        from config import LUNAS_THRESHOLD
        return self.pct_vs_payable >= LUNAS_THRESHOLD

    @property
    def is_overbilling(self):
        from config import OVERBILLING_THRESHOLD
        return self.pct_vs_contract > OVERBILLING_THRESHOLD

    @property
    def progress_pct(self):
        last_pf = None
        for c in sorted(self.certificates, key=lambda x: x.id):
            if c.progress_factor and c.progress_factor > 0:
                last_pf = c.progress_factor
        if last_pf:
            return round(last_pf * 100, 2)
        if self.final_contract <= 0:
            return 0.0
        return round(self.total_paid / self.final_contract * 100, 2)

    @property
    def retention_due_soon(self):
        from config import RETENTION_ALERT_DAYS
        if not self.retention_release_date:
            return False
        delta = (self.retention_release_date - datetime.utcnow().date()).days
        return 0 <= delta <= RETENTION_ALERT_DAYS

    @property
    def segments(self):
        c = self.final_contract
        if c <= 0:
            return {"paid_pct": 0, "remaining_pct": 0, "retention_pct": 0, "overbill": False}
        paid = self.total_paid
        ret = self.retention_amount
        overbill = paid > (c - ret) + 1
        paid_pct = min(paid / c * 100, 100)
        ret_pct = min(ret / c * 100, max(0.0, 100 - paid_pct))
        remaining_pct = max(0.0, 100 - paid_pct - ret_pct)
        return {
            "paid_pct": round(paid_pct, 2),
            "remaining_pct": round(remaining_pct, 2),
            "retention_pct": round(ret_pct, 2),
            "overbill": overbill,
        }

    def to_dict(self):
        return {
            "id": self.id,
            "vendor_id": self.vendor_id,
            "project_id": self.project_id,
            "spk_number": self.spk_number,
            "work_description": self.work_description,
            "contract_value": self.contract_value,
            "total_additions": self.total_additions,
            "total_reductions": self.total_reductions,
            "retention_pct": self.retention_pct,
            "retention_amount": self.retention_amount,
            "retention_release_date": self.retention_release_date.isoformat() if self.retention_release_date else None,
            "total_paid": self.total_paid,
            "payable": self.payable,
            "sisa_bayar": self.sisa_bayar,
            "progress_pct": self.progress_pct,
            "retention_due_soon": self.retention_due_soon,
            "jenis": self.jenis,
            "tanggal_terbit": self.tanggal_terbit.isoformat() if self.tanggal_terbit else None,
            "status": self.status,
            "alokasi_biaya": self.alokasi_biaya,
            "payments": [p.to_dict() for p in self.payments],
        }


class Certificate(db.Model):
    """Sertifikat pembayaran — satu sertifikat bisa punya banyak Payment."""
    __tablename__ = "certificates"

    id = db.Column(db.Integer, primary_key=True)
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id"), nullable=False)
    nomor = db.Column(db.String(100), default="")          # was: payment_number
    periode = db.Column(db.String(10), nullable=True)      # "2026-08"
    tanggal = db.Column(db.Date, nullable=True)
    nilai_tersertifikasi = db.Column(db.Float, default=0.0)
    progress_factor = db.Column(db.Float, nullable=True)
    sertifikat_file = db.Column(db.String(300), nullable=True)
    source = db.Column(db.String(20), default="manual")
    created_by = db.Column(db.String(50), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship("Payment", backref="certificate", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "spk_id": self.spk_id,
            "nomor": self.nomor,
            "periode": self.periode,
            "tanggal": self.tanggal.isoformat() if self.tanggal else None,
            "nilai_tersertifikasi": self.nilai_tersertifikasi,
            "progress_factor": self.progress_factor,
            "sertifikat_file": self.sertifikat_file,
            "source": self.source,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }


class Payment(db.Model):
    """Pembayaran — DP & pencairan retensi tanpa certificate (certificate_id NULL)."""
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id"), nullable=False)
    certificate_id = db.Column(db.Integer, db.ForeignKey("certificates.id"), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=True)   # was String(20) — B2
    is_dp = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(50), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "spk_id": self.spk_id,
            "certificate_id": self.certificate_id,
            "amount": self.amount,
            "date": self.date.isoformat() if self.date else None,
            "is_dp": self.is_dp,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    entity = db.Column(db.String(50), default="")
    entity_id = db.Column(db.Integer, nullable=True)
    detail = db.Column(db.Text, default="")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user,
            "action": self.action,
            "entity": self.entity,
            "entity_id": self.entity_id,
            "detail": self.detail,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        }
