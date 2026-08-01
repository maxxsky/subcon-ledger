"""
Subcon Payment Monitor — Flask App
"""

import os
import json
import shutil
import re
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file)
from werkzeug.utils import secure_filename

import config
from models import (db, Vendor, Project, SPK, Certificate, Payment, AuditLog,
                    BOQItem, RapVersion, RapItem, RiskAllowance, PrelimItem,
                    ProcurementRequest, PriceComparison, SpkStatusLog, Variation,
                    Accrual, CvrPeriod, CvrLine, CvrCommentary)
from parsers.sertifikat import parse_sertifikat
from werkzeug.security import check_password_hash

# ── APP SETUP ────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{config.DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.BACKUP_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

db.init_app(app)

with app.app_context():
    db.create_all()


# ── AUTH HELPERS ─────────────────────────────────────────────
def _verify_password(stored, plain):
    """Verifikasi password — dukung hash werkzeug dan plaintext legacy."""
    if stored and stored.startswith(("scrypt:", "pbkdf2:", "sha256:")):
        try:
            return check_password_hash(stored, plain)
        except ValueError:
            return False
    return stored == plain


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        user_data = config.USERS.get(session["user"], {})
        if user_data.get("role") != "admin":
            flash("Akses ditolak. Hanya admin yang bisa melakukan aksi ini.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    return session.get("user", "")


def _default_project():
    """Proyek default — Fase 1 belum ada UI project, semua SPK nempel ke proyek pertama."""
    p = Project.query.order_by(Project.id).first()
    if not p:
        p = Project(nama="Proyek Default")
        db.session.add(p)
        db.session.flush()
    return p


def _active_project():
    """Proyek aktif dari session, fallback ke proyek pertama."""
    pid = session.get("project_id")
    if pid:
        p = Project.query.get(pid)
        if p:
            return p
    return _default_project()


def _parse_date_str(s):
    """Parse string tanggal YYYY-MM-DD → date object, None kalau invalid."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _sync_rap_kode(spk):
    """Isi rap_kode dari rap_item_id (versi asal) — identitas stabil lintas versi (Fase 7)."""
    if spk.rap_item_id:
        item = RapItem.query.get(spk.rap_item_id)
        spk.rap_kode = item.kode_rap if item else None
    return spk


def _validate_allocation(alokasi, data):
    """alokasi_biaya wajib konsisten dengan FK yang diisi — tanpa opsi 'lain-lain'."""
    if alokasi == "rap_item" and not data.get("rap_item_id"):
        return "alokasi_biaya=rap_item wajib punya rap_item_id"
    if alokasi == "prelim" and not data.get("prelim_item_id"):
        return "alokasi_biaya=prelim wajib punya prelim_item_id"
    if alokasi == "variation" and not data.get("variation_id"):
        return "alokasi_biaya=variation wajib punya variation_id"
    return None


def audit(action, entity="", entity_id=None, detail=""):
    log = AuditLog(
        user=current_user(),
        action=action,
        entity=entity,
        entity_id=entity_id,
        detail=detail
    )
    db.session.add(log)


# ── TEMPLATE HELPERS ─────────────────────────────────────────
@app.context_processor
def inject_globals():
    user = session.get("user", "")
    role = config.USERS.get(user, {}).get("role", "viewer")
    name = config.USERS.get(user, {}).get("name", "")
    projects = Project.query.order_by(Project.nama).all()
    active_project = None
    pid = session.get("project_id")
    if pid:
        active_project = Project.query.get(pid)
    if not active_project and projects:
        active_project = projects[0]
    return {"current_user": user, "current_role": role, "current_name": name,
            "projects": projects, "active_project": active_project,
            "now": datetime.now()}


def fmt_money(val):
    if val is None:
        return "-"
    val = float(val)
    if val < 500:
        return "-"
    if val >= 1_000_000_000:
        return f"{val/1e9:.2f}M"
    elif val >= 1_000_000:
        return f"{val/1e6:.2f}Jt"
    else:
        return f"{val:,.0f}"


app.jinja_env.filters["money"] = fmt_money
app.jinja_env.filters["enumerate"] = lambda seq: list(enumerate(seq))


# ── AUTH ROUTES ──────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user_data = config.USERS.get(username)
        if user_data and _verify_password(user_data["password"], password):
            session["user"] = username
            audit("login")
            db.session.commit()
            return redirect(url_for("dashboard"))
        flash("Username atau password salah.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    if "user" in session:
        audit("logout")
        db.session.commit()
    session.clear()
    return redirect(url_for("login"))


# ── DASHBOARD ────────────────────────────────────────────────
@app.route("/")
@login_required
def dashboard():
    subcons = Vendor.query.order_by(Vendor.name).all()

    grand_contract = sum(s.total_contract for s in subcons)
    grand_final_contract = sum(s.total_final_contract for s in subcons)
    grand_paid = sum(s.total_paid for s in subcons)
    overall_pct = round(grand_paid / grand_contract * 100, 2) if grand_contract > 0 else 0

    overbilling = [s for s in subcons if s.is_overbilling]
    lunas_list = [s for s in subcons if s.is_lunas]

    retention_due = []
    for s in subcons:
        for spk in s.spks:
            if spk.retention_due_soon:
                retention_due.append({"subcon": s.name, "spk": spk.spk_number,
                                      "date": spk.retention_release_date,
                                      "amount": spk.retention_amount})

    retention_schedule = []
    for s in subcons:
        for spk in s.spks:
            if spk.retention_remaining > 0 and spk.retention_due_date:
                days = (datetime.strptime(spk.retention_due_date, "%Y-%m-%d") - datetime.now()).days
                retention_schedule.append({
                    "subcon": s.name,
                    "spk": spk.spk_number[:20],
                    "due": spk.retention_due_date,
                    "amount": spk.retention_amount,
                    "days": days,
                })
    retention_schedule.sort(key=lambda x: x["due"])

    return render_template("dashboard.html",
                           subcons=subcons,
                           grand_contract=grand_contract,
                           grand_final_contract=grand_final_contract,
                           grand_paid=grand_paid,
                           overall_pct=overall_pct,
                           overbilling=overbilling,
                           lunas_list=lunas_list,
                           retention_due=retention_due,
                           retention_schedule=retention_schedule)


# ── API: summary data untuk chart ───────────────────────────
@app.route("/api/summary")
@login_required
def api_summary():
    subcons = Vendor.query.order_by(Vendor.name).all()

    sorted_by_contract = sorted(subcons, key=lambda s: s.total_contract, reverse=True)
    top10 = sorted_by_contract[:10]

    from collections import defaultdict
    monthly = defaultdict(float)
    all_payments = Payment.query.all()
    for p in all_payments:
        if p.date:
            monthly[p.date.strftime("%Y-%m")] += p.amount

    sorted_months = sorted(monthly.keys())
    timeline = sorted_months[-12:] if len(sorted_months) > 12 else sorted_months

    return jsonify({
        "top10": {
            "labels": [s.name[:22] for s in top10],
            "contract": [round(s.total_contract) for s in top10],
            "paid": [round(s.total_paid) for s in top10],
            "remaining": [round(max(s.total_contract - s.total_paid, 0)) for s in top10],
            "pct": [s.pct_vs_contract for s in top10],
        },
        "timeline": {
            "labels": timeline,
            "amounts": [round(monthly[m]) for m in timeline],
        },
        "totals": {
            "subcons": len(subcons),
            "lunas": sum(1 for s in subcons for spk in s.spks if spk.is_lunas),
            "proses": sum(1 for s in subcons for spk in s.spks if not spk.is_lunas),
            "overbilling": sum(1 for s in subcons for spk in s.spks if spk.is_overbilling),
        }
    })


# ── SUBCON LIST ──────────────────────────────────────────────
@app.route("/subcons")
@login_required
def subcon_list():
    subcons = Vendor.query.order_by(Vendor.name).all()
    return render_template("subcon_list.html", subcons=subcons)


@app.route("/subcons/new", methods=["GET", "POST"])
@admin_required
def subcon_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Nama subkon tidak boleh kosong.", "danger")
            return render_template("subcon_form.html")

        existing = Vendor.query.filter(
            db.func.lower(Vendor.name) == name.lower()
        ).first()
        if existing:
            flash(f"Subkon '{name}' sudah ada.", "warning")
            return redirect(url_for("subcon_detail", subcon_id=existing.id))

        vendor = Vendor(name=name)
        db.session.add(vendor)
        db.session.flush()
        audit("add_subcon", "vendor", vendor.id, f"name={name}")
        db.session.commit()
        flash(f"Subkon '{name}' berhasil ditambahkan.", "success")
        return redirect(url_for("subcon_detail", subcon_id=vendor.id))

    return render_template("subcon_form.html")


@app.route("/subcons/<int:subcon_id>")
@login_required
def subcon_detail(subcon_id):
    vendor = Vendor.query.get_or_404(subcon_id)
    return render_template("subcon_detail.html", subcon=vendor)


@app.route("/subcons/<int:subcon_id>/add_spk", methods=["POST"])
@admin_required
def add_spk(subcon_id):
    vendor = Vendor.query.get_or_404(subcon_id)
    spk_number = request.form.get("spk_number", "").strip()
    desc = request.form.get("work_description", "").strip()
    contract = float(request.form.get("contract_value", 0) or 0)
    ret_pct = float(request.form.get("retention_pct", config.DEFAULT_RETENTION_PCT) or config.DEFAULT_RETENTION_PCT)
    ret_date_raw = request.form.get("retention_release_date", "").strip()
    # Default None = "belum dialokasikan" — bisa diatur belakangan via tombol 'atur'
    alokasi = request.form.get("alokasi_biaya") or None

    if not spk_number:
        flash("Nomor SPK/PO tidak boleh kosong.", "danger")
        return redirect(url_for("subcon_detail", subcon_id=subcon_id))

    form_data = {
        "rap_item_id": request.form.get("rap_item_id") or None,
        "prelim_item_id": request.form.get("prelim_item_id") or None,
        "variation_id": request.form.get("variation_id") or None,
    }
    alloc_err = _validate_allocation(alokasi, form_data)
    if alloc_err:
        flash(alloc_err, "danger")
        return redirect(url_for("subcon_detail", subcon_id=subcon_id))

    ret_date = _parse_date_str(ret_date_raw)

    project = _default_project()
    spk = SPK(vendor_id=subcon_id, project_id=project.id,
              spk_number=spk_number, jenis="SPK", alokasi_biaya=alokasi,
              rap_item_id=form_data["rap_item_id"],
              prelim_item_id=form_data["prelim_item_id"],
              variation_id=form_data["variation_id"],
              work_description=desc, contract_value=contract,
              retention_pct=ret_pct, retention_release_date=ret_date)
    _sync_rap_kode(spk)
    db.session.add(spk)
    db.session.flush()
    audit("add_spk", "spk", spk.id,
          f"vendor={vendor.name}, spk={spk_number}, contract={contract}")
    db.session.commit()
    flash(f"SPK '{spk_number}' berhasil ditambahkan.", "success")
    return redirect(url_for("subcon_detail", subcon_id=subcon_id))


# ── UPLOAD SERTIFIKAT ────────────────────────────────────────
@app.route("/upload", methods=["GET", "POST"])
@admin_required
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Pilih file dulu.", "danger")
            return redirect(url_for("upload"))

        if not file.filename.endswith(".xlsx"):
            flash("Hanya file .xlsx yang diterima.", "danger")
            return redirect(url_for("upload"))

        filename = secure_filename(file.filename)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_name = f"{ts}_{filename}"
        save_path = os.path.join(app.config["UPLOAD_FOLDER"], save_name)
        file.save(save_path)

        try:
            result = parse_sertifikat(save_path)
        except ValueError as e:
            os.remove(save_path)
            flash(f"File tidak valid: {e}", "danger")
            return redirect(url_for("upload"))

        session["pending_upload"] = {
            "filepath": save_path,
            "filename": save_name,
            "result": result
        }

        return redirect(url_for("upload_preview"))

    return render_template("upload.html")


def _norm_spk(s):
    return re.sub(r'[\s\-/.]', '', (s or "")).lower()


@app.route("/upload/preview", methods=["GET", "POST"])
@admin_required
def upload_preview():
    pending = session.get("pending_upload")
    if not pending:
        return redirect(url_for("upload"))

    result = pending["result"]
    subcons = Vendor.query.order_by(Vendor.name).all()

    if request.method == "POST":
        added = {"payments": 0, "subcons": 0, "spks": 0}
        errors = []

        def _max_variation(spk_num):
            a, r = 0, 0
            for p in result["payments"]:
                if p.get("spk_number", "").strip() == spk_num:
                    a = max(a, p.get("total_penambahan", 0) or 0)
                    r = max(r, p.get("total_pengurangan", 0) or 0)
            return a, r

        project = _default_project()

        for i, pd in enumerate(result["payments"]):
            if request.form.get(f"confirm_{i}") != "1":
                continue

            mode = request.form.get(f"mode_{i}", "existing")
            spk = None

            if mode == "new":
                name = request.form.get(f"new_name_{i}", "").strip()
                if not name:
                    errors.append(f"SP-{pd['payment_num']}: nama subkon baru kosong.")
                    continue
                vendor = Vendor.query.filter(
                    db.func.lower(Vendor.name) == name.lower()
                ).first()
                if not vendor:
                    vendor = Vendor(name=name)
                    db.session.add(vendor)
                    db.session.flush()
                    audit("add_subcon", "vendor", vendor.id,
                          f"from_sertifikat, name={name}")
                    added["subcons"] += 1

                spk_number = pd.get("spk_number", "").strip()
                spk = SPK.query.filter(
                    SPK.vendor_id == vendor.id,
                    SPK.spk_number == spk_number
                ).first()
                if spk is None:
                    spk = SPK(
                        vendor_id=vendor.id, project_id=project.id,
                        spk_number=spk_number, jenis="SPK", alokasi_biaya=None,
                        work_description=pd.get("work_desc", ""),
                        contract_value=pd.get("contract_value", 0),
                        retention_pct=pd.get("retention_pct", config.DEFAULT_RETENTION_PCT),
                        total_additions=_max_variation(spk_number)[0],
                        total_reductions=_max_variation(spk_number)[1]
                    )
                    _sync_rap_kode(spk)
                    db.session.add(spk)
                    db.session.flush()
                    audit("add_spk", "spk", spk.id,
                          f"from_sertifikat, vendor={vendor.name}, spk={spk_number}")
                    added["spks"] += 1

            else:
                subcon_id = request.form.get(f"subcon_id_{i}")
                spk_id_raw = request.form.get(f"spk_id_{i}")
                if not subcon_id:
                    errors.append(f"SP-{pd['payment_num']}: subkon belum dipilih.")
                    continue
                vendor = Vendor.query.get(int(subcon_id))
                if not vendor:
                    errors.append(f"SP-{pd['payment_num']}: subkon tidak valid.")
                    continue

                if spk_id_raw == "__new__":
                    spk_number = pd.get("spk_number", "").strip()
                    # Cek dulu apakah SPK dengan nomer ini sudah ada
                    spk = SPK.query.filter(
                        SPK.vendor_id == vendor.id,
                        SPK.spk_number == spk_number
                    ).first()
                    if spk is None:
                        spk = SPK(
                            vendor_id=vendor.id, project_id=project.id,
                            spk_number=spk_number, jenis="SPK", alokasi_biaya=None,
                            work_description=pd.get("work_desc", ""),
                            contract_value=pd.get("contract_value", 0),
                            retention_pct=pd.get("retention_pct", config.DEFAULT_RETENTION_PCT),
                            total_additions=_max_variation(spk_number)[0],
                            total_reductions=_max_variation(spk_number)[1]
                        )
                        _sync_rap_kode(spk)
                        db.session.add(spk)
                        db.session.flush()
                        audit("add_spk", "spk", spk.id,
                              f"from_sertifikat, vendor={vendor.name}, spk={spk_number}")
                        added["spks"] += 1
                elif spk_id_raw:
                    spk = SPK.query.get(int(spk_id_raw))
                    if not spk or spk.vendor_id != vendor.id:
                        errors.append(f"SP-{pd['payment_num']}: SPK tidak valid.")
                        continue
                else:
                    errors.append(f"SP-{pd['payment_num']}: SPK belum dipilih.")
                    continue

            pdate = _parse_date_str(pd.get("date", ""))

            # DP — Payment tanpa Certificate
            if pd.get("dp_amount", 0) > 0:
                if not Payment.query.filter_by(spk_id=spk.id, is_dp=True).first():
                    db.session.add(Payment(
                        spk_id=spk.id, amount=pd["dp_amount"], date=pdate,
                        is_dp=True, created_by=current_user()))
                    audit("add_payment", "payment", None,
                          f"source=sertifikat, dp, sp={pd['payment_num']}, amount={pd['dp_amount']}")

            # Payment utama — simpan progress_factor (fisik) di Certificate
            cp = pd.get("cumulative_progress", 0)
            pf = cp if (cp is not None and cp > 0) else None

            # Cek duplikat — overwrite kalo sudah ada (match by certificate nomor)
            existing_cert = Certificate.query.filter_by(
                spk_id=spk.id, nomor=str(pd["payment_num"])
            ).first()
            if existing_cert:
                existing_cert.nilai_tersertifikasi = pd["net_payment"]
                existing_cert.progress_factor = pf
                existing_cert.sertifikat_file = pending["filename"]
                existing_cert.tanggal = pdate
                if existing_cert.payments:
                    ep = existing_cert.payments[0]
                    ep.amount = pd["net_payment"]
                    ep.date = pdate
                    audit("update_payment", "payment", ep.id,
                          f"overwrite, file={pending['filename']}, "
                          f"sp={pd['payment_num']}, amount={pd['net_payment']}")
                else:
                    db.session.add(Payment(
                        spk_id=spk.id, certificate_id=existing_cert.id,
                        amount=pd["net_payment"], date=pdate,
                        is_dp=False, created_by=current_user()))
                    audit("add_payment", "payment", None,
                          f"source=sertifikat, file={pending['filename']}, "
                          f"sp={pd['payment_num']}, amount={pd['net_payment']}")
                added["payments"] += 1
                continue

            cert = Certificate(
                spk_id=spk.id, nomor=str(pd["payment_num"]),
                periode=pdate.strftime("%Y-%m") if pdate else None,
                tanggal=pdate, nilai_tersertifikasi=pd["net_payment"],
                progress_factor=pf, sertifikat_file=pending["filename"],
                source="sertifikat", created_by=current_user())
            db.session.add(cert)
            db.session.flush()
            db.session.add(Payment(
                spk_id=spk.id, certificate_id=cert.id,
                amount=pd["net_payment"], date=pdate,
                is_dp=False, created_by=current_user()))
            db.session.flush()
            audit("add_payment", "payment", None,
                  f"source=sertifikat, file={pending['filename']}, "
                  f"sp={pd['payment_num']}, amount={pd['net_payment']}")
            added["payments"] += 1

        db.session.commit()
        session.pop("pending_upload", None)

        for e in errors:
            flash(e, "warning")
        parts = []
        if added["payments"]:
            parts.append(f"{added['payments']} pembayaran")
        if added["subcons"]:
            parts.append(f"{added['subcons']} subkon baru")
        if added["spks"]:
            parts.append(f"{added['spks']} SPK baru")
        if parts:
            flash("Tersimpan: " + ", ".join(parts) + ".", "success")
        return redirect(url_for("dashboard"))

    for pd in result["payments"]:
        spk = pd.get("spk_number", "").strip()
        name = pd.get("subcon_name", "").strip()
        matched_subcon = None
        matched_spk = None
        confidence = "no_match"

        if spk:
            spk_key = _norm_spk(spk)
            for s in subcons:
                for sk in s.spks:
                    if sk.spk_number and _norm_spk(sk.spk_number) == spk_key:
                        matched_subcon = s
                        matched_spk = sk
                        confidence = "spk"
                        break
                if matched_subcon:
                    break

        if not matched_subcon and name:
            for s in subcons:
                if s.name.strip().lower() == name.lower():
                    matched_subcon = s
                    confidence = "name"
                    break

        if matched_subcon and not matched_spk:
            cv = pd.get("contract_value", 0)
            for sk in matched_subcon.spks:
                if sk.contract_value > 0 and cv > 0 and abs(sk.contract_value - cv) / cv < 0.01:
                    matched_spk = sk
                    break

        pd["_matched_subcon"] = matched_subcon
        pd["_matched_spk"] = matched_spk
        pd["_match_confidence"] = confidence
        # Mode: baru kalo subkon gak ketemu; kalo subkon ketemu pake existing
        pd["_default_mode"] = "existing" if matched_subcon else "new"

    return render_template("upload_preview.html",
                           result=result, subcons=subcons, pending=pending)


@app.route("/upload/cancel")
@admin_required
def upload_cancel():
    pending = session.pop("pending_upload", None)
    if pending and os.path.exists(pending.get("filepath", "")):
        os.remove(pending["filepath"])
    flash("Upload dibatalkan.", "info")
    return redirect(url_for("dashboard"))


# ── MANUAL INPUT ─────────────────────────────────────────────
@app.route("/manual", methods=["GET", "POST"])
@admin_required
def manual_input():
    subcons_list = Vendor.query.order_by(Vendor.name).all()

    if request.method == "POST":
        subcon_id = request.form.get("subcon_id")
        spk_id_raw = request.form.get("spk_id")
        amount = float(request.form.get("amount", 0) or 0)
        date_str = request.form.get("date", "").strip()
        desc = (request.form.get("description", "").strip()
                or f"Manual-Pembayaran")

        if not subcon_id:
            flash("Pilih subkon.", "danger")
            return render_template("manual_input.html", subcons=subcons_list)

        vendor = Vendor.query.get(int(subcon_id))
        if not vendor:
            flash("Subkon tidak valid.", "danger")
            return render_template("manual_input.html", subcons=subcons_list)

        if spk_id_raw == "__new__":
            spk_number = request.form.get("new_spk_number", "").strip()
            if not spk_number:
                flash("Nomor SPK/PO tidak boleh kosong.", "danger")
                return render_template("manual_input.html", subcons=subcons_list)
            alokasi = request.form.get("alokasi_biaya") or None
            form_data = {
                "rap_item_id": request.form.get("rap_item_id") or None,
                "prelim_item_id": None,
                "variation_id": None,
            }
            alloc_err = _validate_allocation(alokasi, form_data)
            if alloc_err:
                flash(alloc_err, "danger")
                return render_template("manual_input.html", subcons=subcons_list)
            project = _default_project()
            spk = SPK(vendor_id=vendor.id, project_id=project.id,
                      spk_number=spk_number, jenis="SPK", alokasi_biaya=alokasi,
                      rap_item_id=form_data["rap_item_id"],
                      work_description=request.form.get("new_work_desc", "").strip(),
                      contract_value=0)
            _sync_rap_kode(spk)
            db.session.add(spk)
            db.session.flush()
            audit("add_spk", "spk", spk.id,
                  f"manual, vendor={vendor.name}, spk={spk_number}")
        elif spk_id_raw:
            spk = SPK.query.get(int(spk_id_raw))
            if not spk or spk.vendor_id != vendor.id:
                flash("SPK tidak valid.", "danger")
                return render_template("manual_input.html", subcons=subcons_list)
        else:
            flash("Pilih SPK.", "danger")
            return render_template("manual_input.html", subcons=subcons_list)

        pdate = _parse_date_str(date_str)

        # Manual payment → Certificate (nilai = amount) + Payment
        cert = Certificate(
            spk_id=spk.id, nomor="", periode=pdate.strftime("%Y-%m") if pdate else None,
            tanggal=pdate, nilai_tersertifikasi=amount,
            source="manual", created_by=current_user())
        db.session.add(cert)
        db.session.flush()
        p = Payment(spk_id=spk.id, certificate_id=cert.id, amount=amount,
                    date=pdate, is_dp=False, created_by=current_user())
        db.session.add(p)
        db.session.flush()
        audit("add_payment", "payment", p.id,
              f"manual, vendor={vendor.name}, spk={spk.spk_number}, amount={amount}")
        db.session.commit()
        flash(f"Pembayaran Rp {amount:,.0f} berhasil ditambahkan.", "success")
        return redirect(url_for("subcon_detail", subcon_id=vendor.id))

    return render_template("manual_input.html", subcons=subcons_list)


# ── API: SPK list for dropdown ─────────────────────────────────
@app.route("/api/subcon/<int:subcon_id>/spks")
@login_required
def api_spks(subcon_id):
    spks = SPK.query.filter_by(vendor_id=subcon_id).all()
    return jsonify([{
        "id": sk.id,
        "spk_number": sk.spk_number,
        "work_description": sk.work_description[:50],
        "contract_value": sk.contract_value,
    } for sk in spks])


# ── AUDIT LOG ────────────────────────────────────────────────
@app.route("/audit")
@login_required
def audit_log():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template("audit_log.html", logs=logs)


# ── EXPORT ───────────────────────────────────────────────────
@app.route("/export")
@login_required
def export_excel():
    from exporters.excel import generate_excel
    output_dir = os.path.join(config.BASE_DIR, "exports")
    os.makedirs(output_dir, exist_ok=True)
    path = generate_excel(Vendor.query.order_by(Vendor.name).all())
    return send_file(path, as_attachment=True,
                     download_name="Monitoring_Pembayaran_Subkon.xlsx")


# ── BACKUP ───────────────────────────────────────────────────
@app.route("/backup")
@admin_required
def manual_backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(config.BACKUP_FOLDER, f"subcon_{ts}.db")
    shutil.copy2(config.DB_PATH, backup_path)
    audit("backup", detail=f"backup created: subcon_{ts}.db")
    db.session.commit()
    flash(f"Backup berhasil: subcon_{ts}.db", "success")
    return redirect(url_for("dashboard"))


@app.route("/payment/<int:payment_id>/delete", methods=["POST"])
@admin_required
def delete_payment(payment_id):
    p = Payment.query.get_or_404(payment_id)
    spk_id = p.spk_id
    audit("delete_payment", "payment", payment_id,
          f"deleted by {current_user()}, amount={p.amount}")
    db.session.delete(p)
    db.session.commit()
    flash("Pembayaran dihapus.", "info")
    # Redirect ke halaman subcon tempat payment berasal
    spk = SPK.query.get(spk_id)
    if spk:
        return redirect(url_for("subcon_detail", subcon_id=spk.vendor_id))
    return redirect(url_for("dashboard"))


# ── PROJECTS ─────────────────────────────────────────────────
@app.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    if request.method == "POST":
        if current_user() and config.USERS.get(current_user(), {}).get("role") != "admin":
            flash("Akses ditolak.", "danger")
            return redirect(url_for("projects"))
        nama = request.form.get("nama", "").strip()
        if not nama:
            flash("Nama proyek tidak boleh kosong.", "danger")
            return redirect(url_for("projects"))
        lokasi = request.form.get("lokasi", "").strip()
        nilai_kontrak = float(request.form.get("nilai_kontrak", 0) or 0)
        margin = request.form.get("margin_tender_pct", "").strip()
        p = Project(nama=nama, lokasi=lokasi, nilai_kontrak=nilai_kontrak,
                    margin_tender_pct=float(margin) if margin else None,
                    tanggal_mulai=_parse_date_str(request.form.get("tanggal_mulai", "")),
                    durasi_rencana_bulan=int(request.form.get("durasi_rencana_bulan", 0) or 0),
                    status=request.form.get("status", "aktif"))
        db.session.add(p)
        db.session.flush()
        audit("add_project", "project", p.id, f"nama={nama}")
        db.session.commit()
        session["project_id"] = p.id
        flash(f"Proyek '{nama}' dibuat dan diaktifkan.", "success")
        return redirect(url_for("rap_view", project_id=p.id))
    return render_template("projects.html")


@app.route("/projects/<int:project_id>/switch")
@login_required
def project_switch(project_id):
    p = Project.query.get_or_404(project_id)
    session["project_id"] = p.id
    flash(f"Proyek aktif: {p.nama}", "info")
    nxt = request.args.get("next", "")
    return redirect(nxt or url_for("dashboard"))


# ── RAP VIEW ─────────────────────────────────────────────────
def _rap_version(project_id, version_id=None):
    """Versi RAP aktif utk proyek — pilih by id, fallback status aktif, lalu draft terbaru."""
    if version_id:
        v = RapVersion.query.filter_by(id=version_id, project_id=project_id).first()
        if v:
            return v
    v = RapVersion.query.filter_by(project_id=project_id, status="aktif") \
                        .order_by(RapVersion.id.desc()).first()
    if v:
        return v
    return RapVersion.query.filter_by(project_id=project_id) \
                           .order_by(RapVersion.id.desc()).first()


@app.route("/projects/<int:project_id>/rap")
@login_required
def rap_view(project_id):
    project = Project.query.get_or_404(project_id)
    session["project_id"] = project_id
    version_id = request.args.get("version", type=int)
    version = _rap_version(project_id, version_id)
    versions = RapVersion.query.filter_by(project_id=project_id) \
                               .order_by(RapVersion.id.desc()).all()
    items = []
    prelim_items = []
    risk_items = []
    boq_items = BOQItem.query.filter_by(project_id=project_id) \
                              .order_by(BOQItem.kode).all()
    if version:
        items = RapItem.query.filter_by(project_id=project_id, rap_version_id=version.id) \
                             .order_by(RapItem.kode_rap).all()
        prelim_items = PrelimItem.query.filter_by(project_id=project_id, rap_version_id=version.id) \
                                       .order_by(PrelimItem.id).all()
        risk_items = RiskAllowance.query.filter_by(project_id=project_id, rap_version_id=version.id) \
                                        .order_by(RiskAllowance.id).all()
    return render_template("rap_view.html", project=project, version=version,
                           versions=versions, items=items, prelim_items=prelim_items,
                           risk_items=risk_items, boq_items=boq_items)


# ── API: versi RAP ────────────────────────────────────────────
@app.route("/api/projects/<int:project_id>/rap/versions", methods=["POST"])
@admin_required
def api_rap_versions(project_id):
    project = Project.query.get_or_404(project_id)
    data = request.get_json(force=True) or {}
    # Supersede versi aktif
    for v in RapVersion.query.filter_by(project_id=project_id, status="aktif").all():
        v.status = "superseded"
    latest = RapVersion.query.filter_by(project_id=project_id) \
                             .order_by(RapVersion.id.desc()).first()
    next_no = (latest.versi if latest and latest.versi.startswith("v") else "v0")
    try:
        next_versi = "v" + str(int(next_no[1:]) + 1)
    except ValueError:
        next_versi = "v1"
    v = RapVersion(project_id=project_id, versi=next_versi, status="aktif",
                   tanggal=_parse_date_str(data.get("tanggal", "")),
                   disusun_oleh=data.get("disusun_oleh", ""),
                   catatan_revisi=data.get("catatan_revisi", ""))
    db.session.add(v)
    db.session.flush()
    audit("add_rap_version", "rap_version", v.id,
          f"project={project.nama}, versi={next_versi}")
    db.session.commit()
    return jsonify(v.to_dict()), 201


# ── API: rap items CRUD ───────────────────────────────────────
@app.route("/api/rap-items", methods=["POST"])
@admin_required
def api_rap_items():
    data = request.get_json(force=True) or {}
    project_id = data.get("project_id")
    version_id = data.get("rap_version_id")
    if not project_id or not version_id:
        return jsonify({"error": "project_id & rap_version_id wajib"}), 400
    version = RapVersion.query.get(version_id)
    if not version or version.project_id != project_id:
        return jsonify({"error": "versi RAP tidak valid"}), 400

    vol_boq = float(data.get("vol_boq", 0) or 0)
    faktor = float(data.get("faktor", 1) or 1)
    hsat = float(data.get("hsat_rap", 0) or 0)
    vol_rap = vol_boq * faktor
    kode_rap = (data.get("kode_rap") or "").strip()
    if not kode_rap:
        return jsonify({"error": "kode_rap wajib terisi — item tanpa kode tidak bisa dilacak komitmennya (Fase 7)"}), 400
    item = RapItem(
        project_id=project_id, rap_version_id=version_id,
        kode_rap=kode_rap,
        boq_item_id=data.get("boq_item_id") or None,
        uraian_baku=data.get("uraian_baku", ""),
        jenis_biaya=data.get("jenis_biaya", "material"),
        satuan=data.get("satuan", ""),
        vol_boq=vol_boq, faktor=faktor, vol_rap=vol_rap,
        hsat_rap=hsat, total_rap=vol_rap * hsat,
        sumber_harga=data.get("sumber_harga", "penawaran"),
        is_consumable=bool(data.get("is_consumable", False)),
        catatan=data.get("catatan", ""))
    db.session.add(item)
    db.session.flush()
    audit("add_rap_item", "rap_item", item.id,
          f"versi={version.versi}, kode={item.kode_rap}, total={item.total_rap}")
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route("/api/rap-items/<int:item_id>", methods=["PATCH"])
@admin_required
def api_rap_items_update(item_id):
    item = RapItem.query.get_or_404(item_id)
    data = request.get_json(force=True) or {}
    if "kode_rap" in data and not (data.get("kode_rap") or "").strip():
        return jsonify({"error": "kode_rap wajib terisi — item tanpa kode tidak bisa dilacak komitmennya (Fase 7)"}), 400
    for k in ("kode_rap", "uraian_baku", "jenis_biaya", "satuan", "sumber_harga", "catatan"):
        if k in data:
            setattr(item, k, data[k])
    if "is_consumable" in data:
        item.is_consumable = bool(data["is_consumable"])
    if "boq_item_id" in data:
        item.boq_item_id = data["boq_item_id"] or None
    if "vol_boq" in data:
        item.vol_boq = float(data["vol_boq"] or 0)
    if "faktor" in data:
        item.faktor = float(data["faktor"] or 1)
    if "hsat_rap" in data:
        item.hsat_rap = float(data["hsat_rap"] or 0)
    # vol_rap = vol_boq × faktor — dihitung server, tidak percaya input
    item.vol_rap = item.vol_boq * item.faktor
    item.total_rap = item.vol_rap * item.hsat_rap
    audit("update_rap_item", "rap_item", item.id,
          f"kode={item.kode_rap}, total={item.total_rap}")
    db.session.commit()
    return jsonify(item.to_dict())


# ── API: four-column (RAP / Terikat / Tersertifikasi / Terbayar) ──
@app.route("/api/projects/<int:project_id>/four-column")
@login_required
def api_four_column(project_id):
    version_id = request.args.get("version", type=int)
    version = _rap_version(project_id, version_id)
    if not version:
        return jsonify({"items": [], "version": None, "totals": {}})
    items = RapItem.query.filter_by(project_id=project_id, rap_version_id=version.id) \
                         .order_by(RapItem.kode_rap).all()
    out = []
    for it in items:
        d = it.to_dict()
        d["sisa"] = d["total_rap"] - d["terikat"]
        out.append(d)
    totals = {
        "rap": sum(i["total_rap"] for i in out),
        "terikat": sum(i["terikat"] for i in out),
        "tersertifikasi": sum(i["tersertifikasi"] for i in out),
        "terbayar": sum(i["terbayar"] for i in out),
        "sisa": sum(i["sisa"] for i in out),
    }
    return jsonify({"items": out, "version": version.to_dict(), "totals": totals})


# ── EXPORT RAP → Excel ───────────────────────────────────────
@app.route("/projects/<int:project_id>/rap/export")
@login_required
def rap_export(project_id):
    from exporters.rap_excel import generate_rap_excel
    project = Project.query.get_or_404(project_id)
    version_id = request.args.get("version", type=int)
    version = _rap_version(project_id, version_id)
    if not version:
        flash("Belum ada versi RAP untuk diexport.", "warning")
        return redirect(url_for("rap_view", project_id=project_id))
    path = generate_rap_excel(project, version)
    return send_file(path, as_attachment=True,
                     download_name=f"RAP_{project.nama[:20]}_{version.versi}.xlsx")


# ── PROCUREMENT REQUESTS ────────────────────────────────────
SPK_STATUS_FLOW = ["draft", "diajukan", "review_pusat", "terbit", "aktif", "selesai"]
PROCUREMENT_STATUS_FLOW = ["draft", "proses", "terbit", "dibatalkan"]


def _validate_price_comparison(pr_id, data, errors):
    """Validasi alasan_tidak_dipilih: wajib kalau lebih murah tapi tidak terpilih."""
    terpilih = bool(data.get("terpilih", False))
    harga = float(data.get("harga", 0) or 0)
    if terpilih:
        return
    # Ada comparison terpilih lain yang lebih mahal dari yang ini?
    others = PriceComparison.query.filter_by(procurement_request_id=pr_id, terpilih=True).all()
    more_expensive = [c for c in others if c.harga > harga]
    if more_expensive and not (data.get("alasan_tidak_dipilih") or "").strip():
        errors.append("alasan_tidak_dipilih wajib diisi: pembanding lebih murah tapi tidak terpilih.")


@app.route("/api/procurement-requests", methods=["POST"])
@admin_required
def api_procurement_requests():
    data = request.get_json(force=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id wajib"}), 400
    pr = ProcurementRequest(
        project_id=project_id,
        rap_item_id=data.get("rap_item_id") or None,
        nomor=data.get("nomor", ""),
        tanggal_ajukan=_parse_date_str(data.get("tanggal_ajukan", "")),
        nilai_ajukan=float(data.get("nilai_ajukan", 0) or 0),
        vendor_terpilih_id=data.get("vendor_terpilih_id") or None,
        status=data.get("status", "draft"),
        catatan=data.get("catatan", ""))
    db.session.add(pr)
    db.session.flush()
    audit("add_procurement_request", "procurement_request", pr.id,
          f"nomor={pr.nomor}, nilai={pr.nilai_ajukan}")
    db.session.commit()
    return jsonify(pr.to_dict()), 201


@app.route("/api/procurement-requests/<int:pr_id>/comparisons", methods=["POST"])
@admin_required
def api_procurement_comparisons(pr_id):
    pr = ProcurementRequest.query.get_or_404(pr_id)
    data = request.get_json(force=True) or {}
    errors = []
    _validate_price_comparison(pr_id, data, errors)
    if errors:
        return jsonify({"error": errors[0]}), 400
    pc = PriceComparison(
        procurement_request_id=pr_id,
        vendor_id=data.get("vendor_id"),
        harga=float(data.get("harga", 0) or 0),
        lingkup_termasuk=data.get("lingkup_termasuk", ""),
        lingkup_tidak_termasuk=data.get("lingkup_tidak_termasuk", ""),
        terpilih=bool(data.get("terpilih", False)),
        alasan_tidak_dipilih=data.get("alasan_tidak_dipilih", ""))
    db.session.add(pc)
    db.session.flush()
    audit("add_price_comparison", "price_comparison", pc.id,
          f"pr={pr.nomor}, vendor={pc.vendor_id}, harga={pc.harga}, terpilih={pc.terpilih}")
    db.session.commit()
    return jsonify(pc.to_dict()), 201


@app.route("/api/procurement-requests/<int:pr_id>/status", methods=["PATCH"])
@admin_required
def api_procurement_status(pr_id):
    pr = ProcurementRequest.query.get_or_404(pr_id)
    data = request.get_json(force=True) or {}
    new_status = data.get("status", "")
    if new_status not in PROCUREMENT_STATUS_FLOW:
        return jsonify({"error": f"status harus salah satu: {', '.join(PROCUREMENT_STATUS_FLOW)}"}), 400
    old = pr.status
    pr.status = new_status
    audit("update_procurement_status", "procurement_request", pr.id,
          f"{old} → {new_status}")
    db.session.commit()
    return jsonify(pr.to_dict())


# ── SPK STATUS (tulis log baru) ─────────────────────────────
@app.route("/api/spks/<int:spk_id>/status", methods=["PATCH"])
@admin_required
def api_spk_status(spk_id):
    spk = SPK.query.get_or_404(spk_id)
    data = request.get_json(force=True) or {}
    new_status = data.get("status", "")
    if new_status not in SPK_STATUS_FLOW:
        return jsonify({"error": f"status harus salah satu: {', '.join(SPK_STATUS_FLOW)}"}), 400
    log = SpkStatusLog(spk_id=spk.id, status=new_status,
                       user=current_user(), catatan=data.get("catatan", ""))
    db.session.add(log)
    spk.status = new_status
    audit("update_spk_status", "spk", spk.id,
          f"→ {new_status} (log #{log.id})")
    db.session.commit()
    return jsonify({"spk_id": spk.id, "status": new_status,
                    "log": log.to_dict(), "lead_time_days": spk.lead_time_days})


@app.route("/api/spks/<int:spk_id>", methods=["PATCH"])
@admin_required
def api_spk_update(spk_id):
    """Edit SPK — utk mengisi alokasi belakangan (SPK dari parser sertifikat)."""
    spk = SPK.query.get_or_404(spk_id)
    data = request.get_json(force=True) or {}
    alokasi = data.get("alokasi_biaya")
    if alokasi is not None:
        # None = "belum dialokasikan"; "" kosong dianggap None
        if alokasi == "":
            alokasi = None
        if alokasi not in (None, "rap_item", "prelim", "variation", "rework", "proyek_lain"):
            return jsonify({"error": "alokasi_biaya tidak valid"}), 400
        alloc_data = {
            "rap_item_id": data.get("rap_item_id"),
            "prelim_item_id": data.get("prelim_item_id"),
            "variation_id": data.get("variation_id"),
        }
        err = _validate_allocation(alokasi, alloc_data)
        if err:
            return jsonify({"error": err}), 400
        spk.alokasi_biaya = alokasi
        spk.rap_item_id = alloc_data["rap_item_id"]
        spk.prelim_item_id = alloc_data["prelim_item_id"]
        spk.variation_id = alloc_data["variation_id"]
        _sync_rap_kode(spk)
    for k in ("spk_number", "work_description", "jenis"):
        if k in data:
            setattr(spk, k, data[k])
    audit("update_spk", "spk", spk.id,
          f"alokasi={spk.alokasi_biaya or 'belum'}, rap_kode={spk.rap_kode or '—'}")
    db.session.commit()
    return jsonify({"spk_id": spk.id, "alokasi_biaya": spk.alokasi_biaya,
                    "rap_item_id": spk.rap_item_id, "rap_kode": spk.rap_kode})


# ── VARIATIONS ──────────────────────────────────────────────
@app.route("/projects/<int:project_id>/variations")
@login_required
def variations_view(project_id):
    project = Project.query.get_or_404(project_id)
    session["project_id"] = project_id
    status_filter = request.args.get("status", "")
    q = Variation.query.filter_by(project_id=project_id)
    if status_filter:
        q = q.filter_by(status_entitlement=status_filter)
    variations = q.order_by(Variation.batas_notice.is_(None),
                            Variation.batas_notice.asc()).all()
    today = date.today()
    due_soon = [v for v in variations
                if v.batas_notice and 0 <= (v.batas_notice - today).days <= 3]
    return render_template("variations.html", project=project,
                           variations=variations, due_soon=due_soon,
                           status_filter=status_filter, today=today)


@app.route("/api/variations", methods=["POST"])
@admin_required
def api_variations():
    data = request.get_json(force=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id wajib"}), 400
    v = Variation(
        project_id=project_id,
        nomor=data.get("nomor"),
        rap_item_id=data.get("rap_item_id") or None,
        sumber=data.get("sumber", "instruksi"),
        tanggal_peristiwa=_parse_date_str(data.get("tanggal_peristiwa", "")),
        tanggal_notice=_parse_date_str(data.get("tanggal_notice", "")),
        batas_notice=_parse_date_str(data.get("batas_notice", "")),
        uraian=data.get("uraian", ""),
        estimasi_biaya=float(data.get("estimasi_biaya", 0) or 0),
        nilai_klaim_value=data.get("nilai_klaim_value"),
        dampak_waktu_hari=data.get("dampak_waktu_hari"),
        status_entitlement=data.get("status_entitlement", "diajukan"),
        cco_ref=data.get("cco_ref"))
    if v.rap_item_id:
        ri = RapItem.query.get(v.rap_item_id)
        v.rap_kode = ri.kode_rap if ri else None
    db.session.add(v)
    db.session.flush()
    audit("add_variation", "variation", v.id,
          f"nomor={v.nomor or '—'}, status={v.status_entitlement}, estimasi={v.estimasi_biaya}")
    db.session.commit()
    return jsonify(v.to_dict()), 201


@app.route("/api/projects/<int:project_id>/variations/due")
@login_required
def api_variations_due(project_id):
    """Variation dengan batas_notice ≤3 hari dari hari ini — alert H-3."""
    today = date.today()
    cutoff = today + timedelta(days=3)
    variations = Variation.query.filter(
        Variation.project_id == project_id,
        Variation.batas_notice.isnot(None),
        Variation.batas_notice <= cutoff,
    ).order_by(Variation.batas_notice.asc()).all()
    return jsonify([v.to_dict() for v in variations])


# ── LEAD TIME PUSAT ─────────────────────────────────────────
@app.route("/api/projects/<int:project_id>/lead-time")
@login_required
def api_lead_time(project_id):
    """Rata-rata + rentang (min-max) lead time per SPK dari status log."""
    spks = SPK.query.filter_by(project_id=project_id).all()
    leads = []
    for spk in spks:
        lt = spk.lead_time_days
        if lt is not None:
            leads.append({"spk_id": spk.id, "spk_number": spk.spk_number, "lead_time_days": lt})
    if not leads:
        return jsonify({"count": 0, "avg": None, "min": None, "max": None, "items": []})
    avg = sum(x["lead_time_days"] for x in leads) / len(leads)
    return jsonify({
        "count": len(leads),
        "avg": round(avg, 1),
        "min": min(x["lead_time_days"] for x in leads),
        "max": max(x["lead_time_days"] for x in leads),
        "items": leads,
    })


# ── PROCUREMENT PIPELINE VIEW ───────────────────────────────
@app.route("/projects/<int:project_id>/procurement")
@login_required
def procurement_view(project_id):
    project = Project.query.get_or_404(project_id)
    session["project_id"] = project_id
    prs = ProcurementRequest.query.filter_by(project_id=project_id) \
                                  .order_by(ProcurementRequest.id.desc()).all()
    return render_template("procurement.html", project=project, prs=prs)


# ── CVR ─────────────────────────────────────────────────────
def _cvr_active_items(project_id):
    """RapItem dari versi RAP aktif utk proyek."""
    version = _rap_version(project_id)
    if not version:
        return []
    return RapItem.query.filter_by(project_id=project_id,
                                   rap_version_id=version.id).all()


@app.route("/projects/<int:project_id>/cvr")
@login_required
def cvr_view(project_id):
    project = Project.query.get_or_404(project_id)
    session["project_id"] = project_id
    periods = CvrPeriod.query.filter_by(project_id=project_id) \
                             .order_by(CvrPeriod.periode.desc()).all()
    period_id = request.args.get("period", type=int)
    period = None
    if period_id:
        period = CvrPeriod.query.get(period_id)
    if not period and periods:
        period = periods[0]
    return render_template("cvr.html", project=project, periods=periods, period=period)


@app.route("/api/projects/<int:project_id>/cvr", methods=["POST"])
@admin_required
def api_cvr_generate(project_id):
    """Generate draft cvr_lines dari data terkini. Kalau periode final → 400 (read-only)."""
    data = request.get_json(force=True) or {}
    periode = data.get("periode", "")
    cutoff = _parse_date_str(data.get("cutoff_date", ""))
    if not periode:
        return jsonify({"error": "periode wajib (format YYYY-MM)"}), 400

    existing = CvrPeriod.query.filter_by(project_id=project_id, periode=periode).first()
    if existing and existing.status == "final":
        return jsonify({"error": "periode sudah final — read-only, tidak bisa generate ulang"}), 400
    if existing:
        # hapus draft lama, regenerate
        for l in existing.lines:
            db.session.delete(l)
        for c in existing.commentaries:
            db.session.delete(c)
        period = existing
    else:
        period = CvrPeriod(project_id=project_id, periode=periode, status="draft",
                           cutoff_date=cutoff, disusun_oleh=current_user())
        db.session.add(period)
    db.session.flush()

    items = _cvr_active_items(project_id)
    for it in items:
        # cost_accrual periode berjalan
        accrual_sum = db.session.query(db.func.coalesce(db.func.sum(Accrual.nilai_estimasi), 0)) \
            .filter(Accrual.rap_item_id == it.id, Accrual.periode == periode).scalar()
        committed = max(it.terikat - it.terbayar, 0.0)
        line = CvrLine(
            cvr_period_id=period.id,
            rap_item_id=it.id,
            value_certified=it.tersertifikasi,
            value_internal=it.value_internal,
            cost_actual=it.terbayar,
            cost_accrual=float(accrual_sum or 0),
            cost_committed_outstanding=committed,
            forecast_cost_to_complete=0,   # manual — judgment manusia
            metode_ctc="",                  # manual
            forecast_final_cost=it.terbayar + float(accrual_sum or 0),  # + CTC (0 utk draft baru)
            # Fase 7: JANGAN campur cost ke value. terikat = biaya (SPK ke vendor),
            # value = pendapatan (bisa ditagih ke owner). Nilai ini titik awal saja,
            # harus ditinjau user sebelum finalize.
            forecast_final_value=it.value_internal,
        )
        db.session.add(line)
    audit("generate_cvr", "cvr_period", period.id, f"periode={periode}, draft")
    db.session.commit()
    return jsonify({"period": period.to_dict(),
                    "lines": [l.to_dict() for l in period.lines]}), 201


@app.route("/api/cvr/<int:period_id>", methods=["PATCH"])
@admin_required
def api_cvr_update(period_id):
    period = CvrPeriod.query.get_or_404(period_id)
    if period.status == "final":
        return jsonify({"error": "periode final — read-only, cvr_lines di-snapshot"}), 400
    data = request.get_json(force=True) or {}
    # Edit field manual pada line tertentu
    line_id = data.get("line_id")
    line = CvrLine.query.get(line_id)
    if not line or line.cvr_period_id != period.id:
        return jsonify({"error": "line tidak valid"}), 400
    if "forecast_cost_to_complete" in data:
        line.forecast_cost_to_complete = float(data["forecast_cost_to_complete"] or 0)
    if "metode_ctc" in data:
        line.metode_ctc = data["metode_ctc"]
    if "catatan" in data:
        line.catatan = data["catatan"]
    if "forecast_final_value" in data:
        line.forecast_final_value = float(data["forecast_final_value"] or 0)
    # hitung ulang forecast final cost
    line.forecast_final_cost = (line.cost_actual + line.cost_accrual
                                + line.forecast_cost_to_complete)
    # Commentary kalau dikirim
    if "commentary" in data and (data.get("commentary") or "").strip():
        db.session.add(CvrCommentary(cvr_period_id=period.id,
                                     teks=data["commentary"].strip(),
                                     penyusun=current_user()))
    audit("update_cvr", "cvr_line", line.id, f"periode={period.periode}")
    db.session.commit()
    return jsonify(line.to_dict())


@app.route("/api/cvr/<int:period_id>/finalize", methods=["POST"])
@admin_required
def api_cvr_finalize(period_id):
    period = CvrPeriod.query.get_or_404(period_id)
    if period.status == "final":
        return jsonify({"error": "sudah final"}), 400
    period.status = "final"
    period.tanggal_final = date.today()
    audit("finalize_cvr", "cvr_period", period.id,
          f"periode={period.periode} — snapshot terkunci")
    db.session.commit()
    return jsonify(period.to_dict())


@app.route("/api/projects/<int:project_id>/cvr/variance")
@login_required
def api_cvr_variance(project_id):
    """Variance forecast periode lama (final) vs terbaru, per rap_item."""
    periods = CvrPeriod.query.filter_by(project_id=project_id) \
                             .order_by(CvrPeriod.periode.asc()).all()
    by_period = {}
    for p in periods:
        for l in p.lines:
            if l.rap_item_id not in by_period:
                by_period[l.rap_item_id] = []
            by_period[l.rap_item_id].append({
                "period": p.periode, "status": p.status,
                "forecast_final_cost": l.forecast_final_cost,
                "forecast_final_value": l.forecast_final_value,
            })
    out = []
    for rap_item_id, entries in by_period.items():
        entries.sort(key=lambda e: e["period"])
        prev = None
        for e in entries:
            if prev is not None:
                out.append({
                    "rap_item_id": rap_item_id,
                    "prev_period": prev["period"],
                    "curr_period": e["period"],
                    "prev_cost": prev["forecast_final_cost"],
                    "curr_cost": e["forecast_final_cost"],
                    "cost_delta": e["forecast_final_cost"] - prev["forecast_final_cost"],
                    "prev_value": prev["forecast_final_value"],
                    "curr_value": e["forecast_final_value"],
                    "value_delta": e["forecast_final_value"] - prev["forecast_final_value"],
                })
            prev = e
    return jsonify(out)


@app.route("/cvr/<int:period_id>/export")
@login_required
def cvr_export(period_id):
    from exporters.cvr_excel import generate_cvr_excel
    period = CvrPeriod.query.get_or_404(period_id)
    project = Project.query.get_or_404(period.project_id)
    path = generate_cvr_excel(project, period)
    return send_file(path, as_attachment=True,
                     download_name=f"CVR_{project.nama[:20]}_{period.periode}.xlsx")


# ── ACCRUALS ────────────────────────────────────────────────
@app.route("/api/accruals", methods=["POST"])
@admin_required
def api_accruals():
    data = request.get_json(force=True) or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id wajib"}), 400
    a = Accrual(
        project_id=project_id,
        rap_item_id=data.get("rap_item_id") or None,
        spk_id=data.get("spk_id") or None,
        periode=data.get("periode", ""),
        nilai_estimasi=float(data.get("nilai_estimasi", 0) or 0),
        dasar=data.get("dasar", ""),
        dibuat_oleh=current_user(),
        tanggal=_parse_date_str(data.get("tanggal", "")))
    db.session.add(a)
    db.session.flush()
    audit("add_accrual", "accrual", a.id,
          f"periode={a.periode}, rap_item={a.rap_item_id}, nilai={a.nilai_estimasi}")
    db.session.commit()
    return jsonify(a.to_dict()), 201


@app.route("/api/projects/<int:project_id>/accruals")
@login_required
def api_accruals_list(project_id):
    periode = request.args.get("periode", "")
    q = Accrual.query.filter_by(project_id=project_id)
    if periode:
        q = q.filter_by(periode=periode)
    accruals = q.order_by(Accrual.periode.desc(), Accrual.id).all()
    return jsonify([a.to_dict() for a in accruals])


# ── VENDOR HISTORY (lintas proyek) ──────────────────────────
@app.route("/api/vendors/<int:vendor_id>/history")
@login_required
def api_vendor_history(vendor_id):
    """Semua SPK untuk vendor, lintas proyek — vendors sengaja tanpa project_id."""
    vendor = Vendor.query.get_or_404(vendor_id)
    spks = SPK.query.filter_by(vendor_id=vendor_id) \
                    .order_by(SPK.tanggal_terbit.is_(None), SPK.tanggal_terbit.asc()).all()
    rows = []
    materials = {}   # uraian_baku → list harga komitmen efektif per unit
    lead_times = []
    for spk in spks:
        project = Project.query.get(spk.project_id) if spk.project_id else None
        lt = spk.lead_time_days
        if lt is not None:
            lead_times.append(lt)
        # Harga komitmen efektif per unit item RAP (final_contract / vol_rap).
        # Hanya kalau SPK mendekati full-scope item (>=80% total_rap) — kalau parsial
        # (misal SPK tambahan 120jt dari item 481.95jt), unit price bakal menyesatkan.
        unit_price = None
        uraian = spk.work_description or ""
        # rap_item di sini = versi RAP yang berlaku saat SPK terbit (jejak historis),
        # lookup eksplisit — RapItem.spks sekarang property berbasis kode, bukan backref.
        rap_item = RapItem.query.get(spk.rap_item_id) if spk.rap_item_id else None
        if rap_item:
            uraian = rap_item.uraian_baku
            full_scope = (rap_item.total_rap > 0
                          and spk.final_contract >= rap_item.total_rap * 0.8)
            if (full_scope and rap_item.vol_rap and rap_item.vol_rap > 0
                    and spk.final_contract > 0):
                unit_price = spk.final_contract / rap_item.vol_rap
        if rap_item and uraian:
            materials.setdefault(uraian, []).append({
                "project_nama": project.nama if project else "—",
                "tanggal_terbit": spk.tanggal_terbit.isoformat() if spk.tanggal_terbit else None,
                "nilai": spk.final_contract,
                "unit_price": unit_price,
                "vol_rap": rap_item.vol_rap if rap_item else None,
                "hsat_rap": rap_item.hsat_rap if rap_item else None,
                "lead_time_hari": lt,
            })
        rows.append({
            "spk_id": spk.id,
            "project_nama": project.nama if project else "—",
            "project_id": spk.project_id,
            "nomor": spk.spk_number,
            "tanggal_terbit": spk.tanggal_terbit.isoformat() if spk.tanggal_terbit else None,
            "nilai": spk.final_contract,
            "rap_item_uraian": uraian,
            "lead_time_hari": lt,
            "status": spk.status,
        })

    # Agregasi harga per material: rata-rata unit price + tren (pertama vs terakhir)
    material_summary = []
    for uraian, entries in sorted(materials.items()):
        priced = [e for e in entries if e["unit_price"] is not None]
        prices = sorted(priced, key=lambda e: e["tanggal_terbit"] or "")
        entry = {
            "uraian": uraian,
            "count": len(entries),
            "entries": entries,
        }
        if prices:
            entry["avg_unit_price"] = sum(e["unit_price"] for e in prices) / len(prices)
            entry["min_unit_price"] = min(e["unit_price"] for e in prices)
            entry["max_unit_price"] = max(e["unit_price"] for e in prices)
            entry["first_price"] = prices[0]["unit_price"]
            entry["last_price"] = prices[-1]["unit_price"]
            entry["trend_pct"] = ((prices[-1]["unit_price"] / prices[0]["unit_price"]) - 1) * 100 if prices[0]["unit_price"] else 0
            entry["avg_hsat_rap"] = sum(e["hsat_rap"] for e in entries if e["hsat_rap"]) / sum(1 for e in entries if e["hsat_rap"]) if any(e["hsat_rap"] for e in entries) else None
        else:
            entry["avg_unit_price"] = None
            entry["min_unit_price"] = None
            entry["max_unit_price"] = None
            entry["first_price"] = None
            entry["last_price"] = None
            entry["trend_pct"] = None
            entry["avg_hsat_rap"] = None
        material_summary.append(entry)

    lt_summary = None
    if lead_times:
        lt_summary = {
            "count": len(lead_times),
            "avg": round(sum(lead_times) / len(lead_times), 1),
            "min": min(lead_times),
            "max": max(lead_times),
            "telat_count": sum(1 for lt in lead_times if lt > 14),
        }

    return jsonify({
        "vendor": vendor.to_dict(),
        "spks": rows,
        "materials": material_summary,
        "lead_time": lt_summary,
    })


@app.route("/vendors/<int:vendor_id>")
@login_required
def vendor_history_view(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    return render_template("vendor_history.html", vendor=vendor)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)