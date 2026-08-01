"""
Subcon Payment Monitor — Flask App
"""

import os
import json
import shutil
import re
from datetime import datetime, date
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file)
from werkzeug.utils import secure_filename

import config
from models import db, Subcon, SPK, Payment, AuditLog
from parsers.sertifikat import parse_sertifikat

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
    return {"current_user": user, "current_role": role, "current_name": name,
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
        if user_data and user_data["password"] == password:
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
    subcons = Subcon.query.order_by(Subcon.name).all()

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
    subcons = Subcon.query.order_by(Subcon.name).all()

    sorted_by_contract = sorted(subcons, key=lambda s: s.total_contract, reverse=True)
    top10 = sorted_by_contract[:10]

    from collections import defaultdict
    monthly = defaultdict(float)
    all_payments = Payment.query.all()
    for p in all_payments:
        d = (p.date or "").strip()
        if len(d) >= 7 and d[4] == "-":
            monthly[d[:7]] += p.amount

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
    subcons = Subcon.query.order_by(Subcon.name).all()
    return render_template("subcon_list.html", subcons=subcons)


@app.route("/subcons/new", methods=["GET", "POST"])
@admin_required
def subcon_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Nama subkon tidak boleh kosong.", "danger")
            return render_template("subcon_form.html")

        existing = Subcon.query.filter(
            db.func.lower(Subcon.name) == name.lower()
        ).first()
        if existing:
            flash(f"Subkon '{name}' sudah ada.", "warning")
            return redirect(url_for("subcon_detail", subcon_id=existing.id))

        subcon = Subcon(name=name)
        db.session.add(subcon)
        db.session.flush()
        audit("add_subcon", "subcon", subcon.id, f"name={name}")
        db.session.commit()
        flash(f"Subkon '{name}' berhasil ditambahkan.", "success")
        return redirect(url_for("subcon_detail", subcon_id=subcon.id))

    return render_template("subcon_form.html")


@app.route("/subcons/<int:subcon_id>")
@login_required
def subcon_detail(subcon_id):
    subcon = Subcon.query.get_or_404(subcon_id)
    return render_template("subcon_detail.html", subcon=subcon)


@app.route("/subcons/<int:subcon_id>/add_spk", methods=["POST"])
@admin_required
def add_spk(subcon_id):
    subcon = Subcon.query.get_or_404(subcon_id)
    spk_number = request.form.get("spk_number", "").strip()
    desc = request.form.get("work_description", "").strip()
    contract = float(request.form.get("contract_value", 0) or 0)
    ret_pct = float(request.form.get("retention_pct", config.DEFAULT_RETENTION_PCT) or config.DEFAULT_RETENTION_PCT)
    ret_date_raw = request.form.get("retention_release_date", "").strip()

    if not spk_number:
        flash("Nomor SPK/PO tidak boleh kosong.", "danger")
        return redirect(url_for("subcon_detail", subcon_id=subcon_id))

    ret_date = None
    if ret_date_raw:
        try:
            ret_date = date.fromisoformat(ret_date_raw)
        except ValueError:
            pass

    spk = SPK(subcon_id=subcon_id, spk_number=spk_number,
              work_description=desc, contract_value=contract,
              retention_pct=ret_pct, retention_release_date=ret_date)
    db.session.add(spk)
    db.session.flush()
    audit("add_spk", "spk", spk.id,
          f"subcon={subcon.name}, spk={spk_number}, contract={contract}")
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
    subcons = Subcon.query.order_by(Subcon.name).all()

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
                subcon = Subcon.query.filter(
                    db.func.lower(Subcon.name) == name.lower()
                ).first()
                if not subcon:
                    subcon = Subcon(name=name)
                    db.session.add(subcon)
                    db.session.flush()
                    audit("add_subcon", "subcon", subcon.id,
                          f"from_sertifikat, name={name}")
                    added["subcons"] += 1

                spk_number = pd.get("spk_number", "").strip()
                spk = SPK.query.filter(
                    SPK.subcon_id == subcon.id,
                    SPK.spk_number == spk_number
                ).first()
                if spk is None:
                    spk = SPK(
                        subcon_id=subcon.id,
                        spk_number=spk_number,
                        work_description=pd.get("work_desc", ""),
                        contract_value=pd.get("contract_value", 0),
                        retention_pct=pd.get("retention_pct", config.DEFAULT_RETENTION_PCT),
                        total_additions=_max_variation(spk_number)[0],
                        total_reductions=_max_variation(spk_number)[1]
                    )
                    db.session.add(spk)
                    db.session.flush()
                    audit("add_spk", "spk", spk.id,
                          f"from_sertifikat, subcon={subcon.name}, spk={spk_number}")
                    added["spks"] += 1

            else:
                subcon_id = request.form.get(f"subcon_id_{i}")
                spk_id_raw = request.form.get(f"spk_id_{i}")
                if not subcon_id:
                    errors.append(f"SP-{pd['payment_num']}: subkon belum dipilih.")
                    continue
                subcon = Subcon.query.get(int(subcon_id))
                if not subcon:
                    errors.append(f"SP-{pd['payment_num']}: subkon tidak valid.")
                    continue

                if spk_id_raw == "__new__":
                    spk_number = pd.get("spk_number", "").strip()
                    # Cek dulu apakah SPK dengan nomer ini sudah ada
                    spk = SPK.query.filter(
                        SPK.subcon_id == subcon.id,
                        SPK.spk_number == spk_number
                    ).first()
                    if spk is None:
                        spk = SPK(
                            subcon_id=subcon.id,
                            spk_number=spk_number,
                            work_description=pd.get("work_desc", ""),
                            contract_value=pd.get("contract_value", 0),
                            retention_pct=pd.get("retention_pct", config.DEFAULT_RETENTION_PCT),
                            total_additions=_max_variation(spk_number)[0],
                            total_reductions=_max_variation(spk_number)[1]
                        )
                        db.session.add(spk)
                        db.session.flush()
                        audit("add_spk", "spk", spk.id,
                              f"from_sertifikat, subcon={subcon.name}, spk={spk_number}")
                        added["spks"] += 1
                elif spk_id_raw:
                    spk = SPK.query.get(int(spk_id_raw))
                    if not spk or spk.subcon_id != subcon.id:
                        errors.append(f"SP-{pd['payment_num']}: SPK tidak valid.")
                        continue
                else:
                    errors.append(f"SP-{pd['payment_num']}: SPK belum dipilih.")
                    continue

            if pd.get("dp_amount", 0) > 0:
                if not Payment.query.filter_by(spk_id=spk.id, is_dp=True).first():
                    db.session.add(Payment(
                        spk_id=spk.id, description="Pembayaran DP / Uang Muka",
                        amount=pd["dp_amount"], date=pd["date"], payment_number=0,
                        is_dp=True, source="sertifikat",
                        sertifikat_file=pending["filename"], created_by=current_user()))

            # Payment utama — simpan progress_factor (fisik) dari G32
            cp = pd.get("cumulative_progress", 0)
            pf = cp if (cp is not None and cp > 0) else None

            # Cek duplikat — overwrite kalo sudah ada
            existing = Payment.query.filter_by(
                spk_id=spk.id, payment_number=pd["payment_num"]
            ).first()
            if existing:
                existing.amount = pd["net_payment"]
                existing.date = pd["date"]
                existing.progress_factor = pf
                existing.sertifikat_file = pending["filename"]
                audit("update_payment", "payment", existing.id,
                      f"overwrite, file={pending['filename']}, "
                      f"sp={pd['payment_num']}, amount={pd['net_payment']}")
                added["payments"] += 1
                continue
            p = Payment(
                spk_id=spk.id, description=pd["payment_desc"], amount=pd["net_payment"],
                date=pd["date"], payment_number=pd["payment_num"], is_dp=False,
                progress_factor=pf,
                source="sertifikat", sertifikat_file=pending["filename"],
                created_by=current_user())
            db.session.add(p)
            db.session.flush()
            audit("add_payment", "payment", p.id,
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
    subcons_list = Subcon.query.order_by(Subcon.name).all()

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

        subcon = Subcon.query.get(int(subcon_id))
        if not subcon:
            flash("Subkon tidak valid.", "danger")
            return render_template("manual_input.html", subcons=subcons_list)

        if spk_id_raw == "__new__":
            spk_number = request.form.get("new_spk_number", "").strip()
            if not spk_number:
                flash("Nomor SPK/PO tidak boleh kosong.", "danger")
                return render_template("manual_input.html", subcons=subcons_list)
            spk = SPK(subcon_id=subcon.id, spk_number=spk_number,
                      work_description=request.form.get("new_work_desc", "").strip(),
                      contract_value=0)
            db.session.add(spk)
            db.session.flush()
            audit("add_spk", "spk", spk.id,
                  f"manual, subcon={subcon.name}, spk={spk_number}")
        elif spk_id_raw:
            spk = SPK.query.get(int(spk_id_raw))
            if not spk or spk.subcon_id != subcon.id:
                flash("SPK tidak valid.", "danger")
                return render_template("manual_input.html", subcons=subcons_list)
        else:
            flash("Pilih SPK.", "danger")
            return render_template("manual_input.html", subcons=subcons_list)

        p = Payment(spk_id=spk.id, description=desc, amount=amount,
                    date=date_str, source="manual", created_by=current_user())
        db.session.add(p)
        db.session.flush()
        audit("add_payment", "payment", p.id,
              f"manual, subcon={subcon.name}, spk={spk.spk_number}, amount={amount}")
        db.session.commit()
        flash(f"Pembayaran Rp {amount:,.0f} berhasil ditambahkan.", "success")
        return redirect(url_for("subcon_detail", subcon_id=subcon.id))

    return render_template("manual_input.html", subcons=subcons_list)


# ── API: SPK list for dropdown ─────────────────────────────────
@app.route("/api/subcon/<int:subcon_id>/spks")
@login_required
def api_spks(subcon_id):
    spks = SPK.query.filter_by(subcon_id=subcon_id).all()
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
    path = generate_excel(output_dir)
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
        return redirect(url_for("subcon_detail", subcon_id=spk.subcon_id))
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)