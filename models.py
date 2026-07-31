"""
Models — SQLAlchemy ORM untuk Subcon Payment Monitor.
Struktur: Subcon → SPK/PO → Payment
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Subcon(db.Model):
    __tablename__ = "subcons"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    spks = db.relationship("SPK", backref="subcon",
                           cascade="all, delete-orphan", lazy=True)

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
        return self.total_contract - self.total_retention

    @property
    def pct_vs_contract(self):
        if self.total_contract <= 0:
            return 0.0
        return round(self.total_paid / self.total_contract * 100, 2)

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
        c = self.total_contract
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
            "total_contract": self.total_contract,
            "total_paid": self.total_paid,
            "total_retention": self.total_retention,
            "payable": self.payable,
            "sisa": max(self.total_contract - self.total_paid, 0),
            "pct_vs_contract": self.pct_vs_contract,
            "pct_vs_payable": self.pct_vs_payable,
            "is_lunas": self.is_lunas,
            "is_overbilling": self.is_overbilling,
        }


class SPK(db.Model):
    __tablename__ = "spks"

    id = db.Column(db.Integer, primary_key=True)
    subcon_id = db.Column(db.Integer, db.ForeignKey("subcons.id"), nullable=False)
    spk_number = db.Column(db.String(200), default="")
    work_description = db.Column(db.String(500), default="")
    contract_value = db.Column(db.Float, default=0.0)
    retention_pct = db.Column(db.Float, default=0.0)
    retention_release_date = db.Column(db.Date, nullable=True)
    total_additions = db.Column(db.Float, default=0.0)
    total_reductions = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        """Tanggal jatuh tempo retensi: 1 tahun setelah progress 100%."""
        from datetime import datetime, timedelta
        # Cari payment pertama yang progressnya >= 99,5%
        pct_100 = None
        for p in sorted(self.payments, key=lambda x: x.payment_number or 0):
            if p.progress_factor and p.progress_factor >= 0.995:
                pct_100 = p
                break
        if not pct_100:
            return None
        try:
            dt = datetime.strptime(pct_100.date, "%Y-%m-%d")
            return (dt + timedelta(days=365)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
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
        for p in sorted(self.payments, key=lambda x: x.payment_number or 0):
            if p.progress_factor and p.progress_factor > 0:
                last_pf = p.progress_factor
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
            "payments": [p.to_dict() for p in self.payments],
        }


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    spk_id = db.Column(db.Integer, db.ForeignKey("spks.id"), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), default="")
    payment_number = db.Column(db.Integer, nullable=True)
    is_dp = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(20), default="manual")
    sertifikat_file = db.Column(db.String(300), nullable=True)
    progress_factor = db.Column(db.Float, nullable=True)
    created_by = db.Column(db.String(50), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "description": self.description,
            "amount": self.amount,
            "date": self.date,
            "payment_number": self.payment_number,
            "is_dp": self.is_dp,
            "source": self.source,
            "sertifikat_file": self.sertifikat_file,
            "progress_factor": self.progress_factor,
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
