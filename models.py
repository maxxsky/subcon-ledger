"""
Models — SQLAlchemy ORM untuk Subcon Ledger.
Struktur: Project → Vendor → SPK/PO → Certificate → Payment
"""
from datetime import datetime, date
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
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id", name="fk_spks_vendor_id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_spks_project_id"), nullable=False)
    # Kolom FK fase berikutnya — int nullable sekarang, constraint ditambah saat tabel tujuan ada
    rap_item_id = db.Column(db.Integer, db.ForeignKey("rap_items.id", name="fk_spks_rap_item_id"), nullable=True)            # FK Fase 2
    rap_kode = db.Column(db.String(50), nullable=True, index=True)   # identitas stabil item LINTAS VERSI (Fase 7)
    procurement_request_id = db.Column(db.Integer, db.ForeignKey("procurement_requests.id", name="fk_spks_procurement_request_id"), nullable=True)  # FK Fase 3
    prelim_item_id = db.Column(db.Integer, db.ForeignKey("prelim_items.id", name="fk_spks_prelim_item_id"), nullable=True)      # FK Fase 2
    variation_id = db.Column(db.Integer, db.ForeignKey("variations.id", name="fk_spks_variation_id"), nullable=True)            # FK Fase 3
    jenis = db.Column(db.String(10), default="SPK")                # "SPK" | "PO"
    tanggal_terbit = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="aktif")
    # alokasi_biaya wajib diisi di level aplikasi, tanpa opsi "lain-lain"
    # alokasi_biaya wajib diisi di level aplikasi, tanpa opsi "lain-lain".
    # TANPA default — None = "belum dialokasikan" (contoh: SPK hasil parser sertifikat).
    # Penting: kalau kolom punya default="rap_item", nilai None eksplisit akan
    # di-override jadi "rap_item" oleh SQLAlchemy — celah yang bikin SPK parser
    # mengaku rap_item padahal tidak menunjuk rap_item manapun.
    alokasi_biaya = db.Column(db.String(20))   # rap_item|prelim|variation|rework|proyek_lain|None

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
    status_logs = db.relationship("SpkStatusLog", backref="spk",
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
    def lead_time_days(self):
        """Hari dari diajukan → terbit, dari spk_status_logs (bukan kolom terpisah)."""
        diajukan = None
        terbit = None
        for log in self.status_logs:
            if log.status == "diajukan" and diajukan is None:
                diajukan = log.timestamp
            elif log.status == "terbit" and terbit is None:
                terbit = log.timestamp
        if diajukan and terbit:
            return (terbit - diajukan).days
        return None

    @property
    def current_status(self):
        """Status terbaru dari log — bukan kolom status SPK itu sendiri."""
        if not self.status_logs:
            return self.status or "draft"
        return self.status_logs[-1].status

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
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id", name="fk_certificates_spk_id"), nullable=False)
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
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id", name="fk_payments_spk_id"), nullable=False)
    certificate_id = db.Column(db.Integer, db.ForeignKey("certificates.id", name="fk_payments_certificate_id"), nullable=True)
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


class BOQItem(db.Model):
    """Bill of Quantity — baseline penawaran, sumber harga satuan jual."""
    __tablename__ = "boq_items"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_boq_items_project_id"), nullable=False)
    kode = db.Column(db.String(50), default="")
    uraian = db.Column(db.String(300), default="")
    satuan = db.Column(db.String(20), default="")
    volume = db.Column(db.Float, default=0.0)
    harga_satuan_jual = db.Column(db.Float, default=0.0)
    total_jual = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rap_items = db.relationship("RapItem", backref="boq_item", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "kode": self.kode,
            "uraian": self.uraian,
            "satuan": self.satuan,
            "volume": self.volume,
            "harga_satuan_jual": self.harga_satuan_jual,
            "total_jual": self.total_jual,
        }


class RapVersion(db.Model):
    """Versi RAP — baseline dibekukan, revisi = versi baru bukan overwrite."""
    __tablename__ = "rap_versions"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_rap_versions_project_id"), nullable=False)
    versi = db.Column(db.String(20), default="v1")
    tanggal = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="draft")   # draft|aktif|superseded
    disusun_oleh = db.Column(db.String(100), default="")
    catatan_revisi = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("RapItem", backref="version",
                            cascade="all, delete-orphan", lazy=True)
    risk_allowances = db.relationship("RiskAllowance", backref="version",
                                      cascade="all, delete-orphan", lazy=True)
    prelim_items = db.relationship("PrelimItem", backref="version",
                                   cascade="all, delete-orphan", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "versi": self.versi,
            "tanggal": self.tanggal.isoformat() if self.tanggal else None,
            "status": self.status,
            "disusun_oleh": self.disusun_oleh,
            "catatan_revisi": self.catatan_revisi,
        }


class RapItem(db.Model):
    """Satu baris RAP = satu keputusan pengadaan."""
    __tablename__ = "rap_items"
    __table_args__ = (
        db.UniqueConstraint("project_id", "rap_version_id", "kode_rap",
                            name="uq_rap_item_proyek_versi_kode"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_rap_items_project_id"), nullable=False)
    rap_version_id = db.Column(db.Integer, db.ForeignKey("rap_versions.id", name="fk_rap_items_rap_version_id"), nullable=False)
    kode_rap = db.Column(db.String(50), default="")
    boq_item_id = db.Column(db.Integer, db.ForeignKey("boq_items.id", name="fk_rap_items_boq_item_id"), nullable=True)
    uraian_baku = db.Column(db.String(300), default="")
    jenis_biaya = db.Column(db.String(20), default="material")  # material|upah|alat|subkon|overhead
    satuan = db.Column(db.String(20), default="")
    vol_boq = db.Column(db.Float, default=0.0)
    faktor = db.Column(db.Float, default=1.0)      # waste/overlap eksplisit
    vol_rap = db.Column(db.Float, default=0.0)     # = vol_boq × faktor
    hsat_rap = db.Column(db.Float, default=0.0)
    total_rap = db.Column(db.Float, default=0.0)
    sumber_harga = db.Column(db.String(20), default="penawaran")  # penawaran|historis|asumsi
    is_consumable = db.Column(db.Boolean, default=False)
    catatan = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── SPK yang menunjuk item ini LINTAS VERSI RAP — via kode_rap, bukan id (Fase 7) ──
    # rap_item baru dibuat tiap revisi RAP, tapi SPK tetap menunjuk barang yang sama.
    # Kalau pakai FK id, terikat jadi nol setiap kali RAP direvisi.
    @property
    def spks(self):
        if not self.kode_rap:
            return []
        return SPK.query.filter_by(
            project_id=self.project_id,
            rap_kode=self.kode_rap,
        ).all()

    # ── Variation yang menunjuk item ini LINTAS VERSI — pola sama seperti spks ──
    @property
    def variations(self):
        if not self.kode_rap:
            return []
        return Variation.query.filter_by(
            project_id=self.project_id,
            rap_kode=self.kode_rap,
        ).all()

    # ── Angka turunan (on-query, tidak disimpan) ──
    @property
    def terikat(self):
        """Σ spk.final_contract untuk SPK aktif (status != dibatalkan) yang nunjuk item ini."""
        total = 0.0
        for spk in self.spks:
            if spk.status != "dibatalkan":
                total += spk.final_contract
        return total

    @property
    def sisa_budget(self):
        return self.total_rap - self.terikat

    @property
    def buying_gain(self):
        # Sama rumus dengan sisa_budget, beda makna — tampil terpisah
        return self.total_rap - self.terikat

    @property
    def vol_aktual(self):
        # Fase ini belum ada tracking vol aktual — default = vol_rap.
        # Fase berikutnya (sertifikat) mengisi nilai sebenarnya.
        return self.vol_rap

    @property
    def flexed_budget(self):
        # Fase 7: vol_aktual belum punya sumber data — flexed_budget TIDAK ditampilkan
        # di view manapun sampai ada volume aktual dari lapangan (angka yang selalu
        # sama dengan baseline lebih menyesatkan daripada tidak ada).
        return None

    @property
    def tersertifikasi(self):
        """Σ certificate.nilai_tersertifikasi via SPK yang rap_item_id-nya cocok."""
        total = 0.0
        for spk in self.spks:
            for cert in spk.certificates:
                total += cert.nilai_tersertifikasi or 0.0
        return total

    @property
    def terbayar(self):
        """Σ payment.amount via SPK yang sama."""
        total = 0.0
        for spk in self.spks:
            for p in spk.payments:
                total += p.amount
        return total

    @property
    def value_internal(self):
        """Value internal: tersertifikasi + klaim variation (disetujui/diajukan, bukan anticipated)."""
        total = self.tersertifikasi
        for v in self.variations:
            if v.status_entitlement in ("disetujui", "diajukan") and v.nilai_klaim_value:
                total += v.nilai_klaim_value
        return total

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "rap_version_id": self.rap_version_id,
            "kode_rap": self.kode_rap,
            "boq_item_id": self.boq_item_id,
            "uraian_baku": self.uraian_baku,
            "jenis_biaya": self.jenis_biaya,
            "satuan": self.satuan,
            "vol_boq": self.vol_boq,
            "faktor": self.faktor,
            "vol_rap": self.vol_rap,
            "hsat_rap": self.hsat_rap,
            "total_rap": self.total_rap,
            "sumber_harga": self.sumber_harga,
            "is_consumable": self.is_consumable,
            "catatan": self.catatan,
            "terikat": self.terikat,
            "sisa_budget": self.sisa_budget,
            "buying_gain": self.buying_gain,
            "tersertifikasi": self.tersertifikasi,
            "terbayar": self.terbayar,
            "value_internal": self.value_internal,
        }


class RiskAllowance(db.Model):
    """Cadangan risiko RAP — aktif | terpakai | dilepas."""
    __tablename__ = "risk_allowances"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_risk_allowances_project_id"), nullable=False)
    rap_version_id = db.Column(db.Integer, db.ForeignKey("rap_versions.id", name="fk_risk_allowances_rap_version_id"), nullable=False)
    nama = db.Column(db.String(200), default="")
    nilai = db.Column(db.Float, default=0.0)
    pemicu = db.Column(db.String(300), default="")
    status = db.Column(db.String(20), default="aktif")   # aktif|terpakai|dilepas
    nilai_terpakai = db.Column(db.Float, default=0.0)
    tanggal_perubahan = db.Column(db.Date, nullable=True)
    catatan = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "rap_version_id": self.rap_version_id,
            "nama": self.nama,
            "nilai": self.nilai,
            "pemicu": self.pemicu,
            "status": self.status,
            "nilai_terpakai": self.nilai_terpakai,
            "tanggal_perubahan": self.tanggal_perubahan.isoformat() if self.tanggal_perubahan else None,
            "catatan": self.catatan,
        }


class PrelimItem(db.Model):
    """Item preliminaries — biaya per bulan × durasi."""
    __tablename__ = "prelim_items"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_prelim_items_project_id"), nullable=False)
    rap_version_id = db.Column(db.Integer, db.ForeignKey("rap_versions.id", name="fk_prelim_items_rap_version_id"), nullable=False)
    uraian = db.Column(db.String(300), default="")
    biaya_per_bulan = db.Column(db.Float, default=0.0)
    durasi_rencana_bulan = db.Column(db.Integer, default=0)
    total = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    spks = db.relationship("SPK", backref="prelim_item", lazy=True)

    @property
    def terikat(self):
        total = 0.0
        for spk in self.spks:
            if spk.status != "dibatalkan":
                total += spk.final_contract
        return total

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "rap_version_id": self.rap_version_id,
            "uraian": self.uraian,
            "biaya_per_bulan": self.biaya_per_bulan,
            "durasi_rencana_bulan": self.durasi_rencana_bulan,
            "total": self.total,
            "terikat": self.terikat,
        }


class ProcurementRequest(db.Model):
    """Permintaan pengadaan — sumber SPK/PO terbit."""
    __tablename__ = "procurement_requests"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_procurement_requests_project_id"), nullable=False)
    rap_item_id = db.Column(db.Integer, db.ForeignKey("rap_items.id", name="fk_procurement_requests_rap_item_id"), nullable=True)
    nomor = db.Column(db.String(100), default="")
    tanggal_ajukan = db.Column(db.Date, nullable=True)
    nilai_ajukan = db.Column(db.Float, default=0.0)
    vendor_terpilih_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), default="draft")  # draft|proses|terbit|dibatalkan
    catatan = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comparisons = db.relationship("PriceComparison", backref="procurement_request",
                                  cascade="all, delete-orphan", lazy=True)

    @property
    def lead_time_days(self):
        """Hari dari diajukan → terbit (via SPK status log jika ada)."""
        if self.tanggal_ajukan:
            spk = SPK.query.filter_by(procurement_request_id=self.id).first()
            if spk:
                lt = spk.lead_time_days
                if lt is not None:
                    return lt
            return (date.today() - self.tanggal_ajukan).days
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "rap_item_id": self.rap_item_id,
            "nomor": self.nomor,
            "tanggal_ajukan": self.tanggal_ajukan.isoformat() if self.tanggal_ajukan else None,
            "nilai_ajukan": self.nilai_ajukan,
            "vendor_terpilih_id": self.vendor_terpilih_id,
            "status": self.status,
            "catatan": self.catatan,
            "lead_time_days": self.lead_time_days,
        }


class PriceComparison(db.Model):
    """Pembanding harga pengadaan. alasan_tidak_dipilih WAJIB kalau lebih murah tapi tidak terpilih."""
    __tablename__ = "price_comparisons"

    id = db.Column(db.Integer, primary_key=True)
    procurement_request_id = db.Column(db.Integer, db.ForeignKey("procurement_requests.id", name="fk_price_comparisons_procurement_request_id"), nullable=False)
    vendor_id = db.Column(db.Integer, nullable=True)  # nullable — vendor pembanding bisa tidak terdaftar (contoh vendor_id 99)
    harga = db.Column(db.Float, default=0.0)
    lingkup_termasuk = db.Column(db.String(300), default="")
    lingkup_tidak_termasuk = db.Column(db.String(300), default="")
    terpilih = db.Column(db.Boolean, default=False)
    alasan_tidak_dipilih = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "procurement_request_id": self.procurement_request_id,
            "vendor_id": self.vendor_id,
            "harga": self.harga,
            "lingkup_termasuk": self.lingkup_termasuk,
            "lingkup_tidak_termasuk": self.lingkup_tidak_termasuk,
            "terpilih": self.terpilih,
            "alasan_tidak_dipilih": self.alasan_tidak_dipilih,
        }


class SpkStatusLog(db.Model):
    """Riwayat status SPK — tiap perubahan = baris baru, bukan menimpa.
    Flow: draft → diajukan → review_pusat → terbit → aktif → selesai"""
    __tablename__ = "spk_status_logs"

    id = db.Column(db.Integer, primary_key=True)
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id", name="fk_spk_status_logs_spk_id"), nullable=False)
    status = db.Column(db.String(30), default="draft")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.Column(db.String(50), default="")
    catatan = db.Column(db.String(300), default="")

    def to_dict(self):
        return {
            "id": self.id,
            "spk_id": self.spk_id,
            "status": self.status,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "user": self.user,
            "catatan": self.catatan,
        }


class Variation(db.Model):
    """Register variation order — disputed tetap dihitung sebagai cost."""
    __tablename__ = "variations"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_variations_project_id"), nullable=False)
    nomor = db.Column(db.String(50), nullable=True)   # nullable — VAR-004 anticipated tanpa nomor
    rap_item_id = db.Column(db.Integer, db.ForeignKey("rap_items.id", name="fk_variations_rap_item_id"), nullable=True)
    rap_kode = db.Column(db.String(50), nullable=True, index=True)   # identitas stabil LINTAS VERSI (Fase 7)
    sumber = db.Column(db.String(30), default="instruksi")  # instruksi|revisi_gambar|revisi_spek|delay_owner
    tanggal_peristiwa = db.Column(db.Date, nullable=True)
    tanggal_notice = db.Column(db.Date, nullable=True)
    batas_notice = db.Column(db.Date, nullable=True)
    uraian = db.Column(db.String(500), default="")
    estimasi_biaya = db.Column(db.Float, default=0.0)
    nilai_klaim_value = db.Column(db.Float, nullable=True)
    dampak_waktu_hari = db.Column(db.Integer, nullable=True)
    status_entitlement = db.Column(db.String(30), default="diajukan")
    # anticipated|notice_terkirim|diajukan|disetujui|ditolak|disputed
    cco_ref = db.Column(db.String(50), nullable=True)
    catatan = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    spks = db.relationship("SPK", backref="variation", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "nomor": self.nomor,
            "rap_item_id": self.rap_item_id,
            "sumber": self.sumber,
            "tanggal_peristiwa": self.tanggal_peristiwa.isoformat() if self.tanggal_peristiwa else None,
            "tanggal_notice": self.tanggal_notice.isoformat() if self.tanggal_notice else None,
            "batas_notice": self.batas_notice.isoformat() if self.batas_notice else None,
            "uraian": self.uraian,
            "estimasi_biaya": self.estimasi_biaya,
            "nilai_klaim_value": self.nilai_klaim_value,
            "dampak_waktu_hari": self.dampak_waktu_hari,
            "status_entitlement": self.status_entitlement,
            "cco_ref": self.cco_ref,
            "catatan": self.catatan,
        }


class Accrual(db.Model):
    """Estimasi biaya yang belum tersertifikasi — opname lapangan jujur lebih baik dari nol."""
    __tablename__ = "accruals"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_accruals_project_id"), nullable=False)
    rap_item_id = db.Column(db.Integer, db.ForeignKey("rap_items.id", name="fk_accruals_rap_item_id"), nullable=True)
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id", name="fk_accruals_spk_id"), nullable=True)
    periode = db.Column(db.String(10), default="")     # "2026-07"
    nilai_estimasi = db.Column(db.Float, default=0.0)
    dasar = db.Column(db.String(500), default="")
    dibuat_oleh = db.Column(db.String(50), default="")
    tanggal = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "rap_item_id": self.rap_item_id,
            "spk_id": self.spk_id,
            "periode": self.periode,
            "nilai_estimasi": self.nilai_estimasi,
            "dasar": self.dasar,
            "dibuat_oleh": self.dibuat_oleh,
            "tanggal": self.tanggal.isoformat() if self.tanggal else None,
        }


class CvrPeriod(db.Model):
    """Periode CVR — draft bisa diedit, final terkunci (snapshot)."""
    __tablename__ = "cvr_periods"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", name="fk_cvr_periods_project_id"), nullable=False)
    periode = db.Column(db.String(10), default="")     # "2026-06"
    cutoff_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(10), default="draft")  # draft|final
    disusun_oleh = db.Column(db.String(100), default="")
    tanggal_final = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lines = db.relationship("CvrLine", backref="period",
                            cascade="all, delete-orphan", lazy=True)
    commentaries = db.relationship("CvrCommentary", backref="period",
                                   cascade="all, delete-orphan", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "periode": self.periode,
            "cutoff_date": self.cutoff_date.isoformat() if self.cutoff_date else None,
            "status": self.status,
            "disusun_oleh": self.disusun_oleh,
            "tanggal_final": self.tanggal_final.isoformat() if self.tanggal_final else None,
        }


class CvrLine(db.Model):
    """Baris CVR per rap_item — di-snapshot saat final, TIDAK dihitung ulang."""
    __tablename__ = "cvr_lines"

    id = db.Column(db.Integer, primary_key=True)
    cvr_period_id = db.Column(db.Integer, db.ForeignKey("cvr_periods.id", name="fk_cvr_lines_cvr_period_id"), nullable=False)
    rap_item_id = db.Column(db.Integer, db.ForeignKey("rap_items.id", name="fk_cvr_lines_rap_item_id"), nullable=True)
    value_certified = db.Column(db.Float, default=0.0)
    value_internal = db.Column(db.Float, default=0.0)
    cost_actual = db.Column(db.Float, default=0.0)
    cost_accrual = db.Column(db.Float, default=0.0)
    cost_committed_outstanding = db.Column(db.Float, default=0.0)
    forecast_cost_to_complete = db.Column(db.Float, default=0.0)   # manual — judgment manusia
    metode_ctc = db.Column(db.String(30), default="")               # sisa_lingkup|ekstrapolasi|bottom_up
    forecast_final_cost = db.Column(db.Float, default=0.0)
    forecast_final_value = db.Column(db.Float, default=0.0)
    catatan = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rap_item = db.relationship("RapItem", foreign_keys=[rap_item_id], lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "cvr_period_id": self.cvr_period_id,
            "rap_item_id": self.rap_item_id,
            "value_certified": self.value_certified,
            "value_internal": self.value_internal,
            "cost_actual": self.cost_actual,
            "cost_accrual": self.cost_accrual,
            "cost_committed_outstanding": self.cost_committed_outstanding,
            "forecast_cost_to_complete": self.forecast_cost_to_complete,
            "metode_ctc": self.metode_ctc,
            "forecast_final_cost": self.forecast_final_cost,
            "forecast_final_value": self.forecast_final_value,
            "catatan": self.catatan,
        }


class CvrCommentary(db.Model):
    """Catatan naratif CVR per periode."""
    __tablename__ = "cvr_commentaries"

    id = db.Column(db.Integer, primary_key=True)
    cvr_period_id = db.Column(db.Integer, db.ForeignKey("cvr_periods.id", name="fk_cvr_commentaries_cvr_period_id"), nullable=False)
    teks = db.Column(db.Text, default="")
    penyusun = db.Column(db.String(50), default="")

    def to_dict(self):
        return {
            "id": self.id,
            "cvr_period_id": self.cvr_period_id,
            "teks": self.teks,
            "penyusun": self.penyusun,
        }
