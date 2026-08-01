"""
Seed data dummy (03-dummy-data.md) ke test DB terpisah — data/subcon_test.db.

JANGAN jalanin terhadap data/subcon.db (live) — dummy & asli TIDAK boleh campur.
Gue pakai test DB terpisah supaya live data Fase 1 (143 payment asli) tetap bersih.

Scope Fase 2: projects, boq_items, rap_versions, rap_items, risk_allowances,
prelim_items, vendors, spks, certificates, payments.
Fase 3+: procurement_requests, price_comparisons, variations, spk_status_logs,
accruals, cvr_* — di-skip (tabel belum ada / fase berikutnya).

Jalankan: venv/bin/python scripts/seed_dummy.py
"""
import os
import sys
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DB = os.path.join(BASE, "data", "subcon_test.db")

os.environ["SUBCON_DB_PATH"] = TEST_DB

sys.path.insert(0, BASE)

# Import models langsung (tanpa app) — engine manual ke test DB
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import (db, Project, BOQItem, RapVersion, RapItem,
                    RiskAllowance, PrelimItem, Vendor, SPK, Certificate, Payment,
                    ProcurementRequest, PriceComparison, SpkStatusLog, Variation,
                    Accrual, CvrPeriod, CvrLine, CvrCommentary)

engine = create_engine(f"sqlite:///{TEST_DB}")
db.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
s = Session()


def d(x):
    return date.fromisoformat(x) if x else None


def dt(x):
    return datetime.fromisoformat(x) if x else None


def main():
    # ── projects ──
    s.add_all([
        Project(id=1, nama="Gedung Kantor Contoh — Sumbawa", lokasi="Sumbawa Barat, NTB",
                nilai_kontrak=45000000000, margin_tender_pct=9.0,
                tanggal_mulai=d("2026-03-01"), durasi_rencana_bulan=18, status="aktif"),
        Project(id=2, nama="Ruko Contoh — Mataram", lokasi="Mataram, NTB",
                nilai_kontrak=8000000000, margin_tender_pct=11.0,
                tanggal_mulai=d("2026-06-01"), durasi_rencana_bulan=8, status="aktif"),
    ])

    # ── boq_items ──
    s.add_all([
        BOQItem(id=1, project_id=1, kode="3.2", uraian="Pek. Struktur Beton Lt. 2",
                satuan="ls", volume=1, harga_satuan_jual=1400000000, total_jual=1400000000),
        BOQItem(id=2, project_id=1, kode="3.3", uraian="Pek. Bekisting Kolom & Balok Lt. 2",
                satuan="m2", volume=1200, harga_satuan_jual=275000, total_jual=330000000),
        BOQItem(id=3, project_id=1, kode="3.5", uraian="Pek. Waterproofing Atap",
                satuan="m2", volume=450, harga_satuan_jual=185000, total_jual=83250000),
    ])

    # ── rap_versions ──
    s.add_all([
        RapVersion(id=1, project_id=1, versi="v1.0", tanggal=d("2026-03-05"),
                   status="superseded", disusun_oleh="Brahma",
                   catatan_revisi="Baseline awal dari AHS tender"),
        RapVersion(id=2, project_id=1, versi="v1.1", tanggal=d("2026-05-10"),
                   status="aktif", disusun_oleh="Brahma",
                   catatan_revisi="Revisi harga besi setelah SPK-001 terbit; item 3.2.1 dikoreksi"),
    ])

    # ── rap_items ──
    s.add_all([
        RapItem(id=101, project_id=1, rap_version_id=1, kode_rap="3.2.1", boq_item_id=1,
                uraian_baku="Beton Ready Mix K-300", jenis_biaya="material", satuan="m3",
                vol_boq=450, faktor=1.03, vol_rap=463.5, hsat_rap=950000,
                total_rap=440325000, sumber_harga="penawaran", is_consumable=False),
        RapItem(id=102, project_id=1, rap_version_id=2, kode_rap="3.2.1", boq_item_id=1,
                uraian_baku="Beton Ready Mix K-300", jenis_biaya="material", satuan="m3",
                vol_boq=450, faktor=1.03, vol_rap=463.5, hsat_rap=1030000,
                total_rap=477405000, sumber_harga="historis", is_consumable=False,
                catatan="Dikoreksi dari SPK-001 aktual (v1: 950rb → v2: 1.03jt)"),
        RapItem(id=103, project_id=1, rap_version_id=2, kode_rap="3.2.2", boq_item_id=1,
                uraian_baku="Besi Ulir D16", jenis_biaya="material", satuan="kg",
                vol_boq=34000, faktor=1.05, vol_rap=35700, hsat_rap=13500,
                total_rap=481950000, sumber_harga="penawaran", is_consumable=False),
        RapItem(id=104, project_id=1, rap_version_id=2, kode_rap="3.2.3", boq_item_id=1,
                uraian_baku="Besi Ulir D13", jenis_biaya="material", satuan="kg",
                vol_boq=24000, faktor=1.05, vol_rap=25200, hsat_rap=13200,
                total_rap=332640000, sumber_harga="penawaran", is_consumable=False),
        RapItem(id=105, project_id=1, rap_version_id=2, kode_rap="3.2.4", boq_item_id=1,
                uraian_baku="Upah Cor + Alat", jenis_biaya="upah", satuan="m3",
                vol_boq=450, faktor=1.0, vol_rap=450, hsat_rap=85000,
                total_rap=38250000, sumber_harga="historis", is_consumable=False),
        RapItem(id=106, project_id=1, rap_version_id=2, kode_rap="3.3.1", boq_item_id=2,
                uraian_baku="Bekisting Kolom & Balok", jenis_biaya="subkon", satuan="m2",
                vol_boq=1200, faktor=1.0, vol_rap=1200, hsat_rap=240000,
                total_rap=288000000, sumber_harga="penawaran", is_consumable=False),
        RapItem(id=107, project_id=1, rap_version_id=2, kode_rap="3.5.1", boq_item_id=3,
                uraian_baku="Waterproofing Membrane Bakar", jenis_biaya="subkon", satuan="m2",
                vol_boq=450, faktor=1.0, vol_rap=450, hsat_rap=165000,
                total_rap=74250000, sumber_harga="penawaran", is_consumable=False),
        RapItem(id=108, project_id=1, rap_version_id=2, kode_rap="CONS.001",
                boq_item_id=None, uraian_baku="Bahan Habis Pakai Umum (paku, kawat, dll)",
                jenis_biaya="material", satuan="ls", vol_boq=None, faktor=None,
                vol_rap=None, hsat_rap=None, total_rap=45000000,
                sumber_harga="historis", is_consumable=True,
                catatan="Plafon bulanan, bukan per-item. Lihat metode §6."),
    ])

    # ── risk_allowances ──
    s.add_all([
        RiskAllowance(id=1, project_id=1, rap_version_id=2, nama="Eskalasi harga besi >8%",
                      nilai=140000000, pemicu="Harga besi naik >8% dari AHS tender",
                      status="terpakai", nilai_terpakai=140000000,
                      tanggal_perubahan=d("2026-05-10"),
                      catatan="Terpakai penuh — jadi dasar revisi RAP v1.1"),
        RiskAllowance(id=2, project_id=1, rap_version_id=2,
                      nama="Keterlambatan approval gambar 1 bln",
                      nilai=90000000, pemicu="Approval MK >30 hari dari submit",
                      status="aktif", nilai_terpakai=0),
        RiskAllowance(id=3, project_id=1, rap_version_id=2,
                      nama="Curah hujan di atas normal",
                      nilai=70000000, pemicu="Hari hujan >150% rata-rata historis bulan berjalan",
                      status="dilepas", nilai_terpakai=0, tanggal_perubahan=d("2026-07-01"),
                      catatan="Musim kemarau berjalan normal, dilepas per Juli"),
    ])

    # ── prelim_items ──
    s.add_all([
        PrelimItem(id=1, project_id=1, rap_version_id=2, uraian="Direksi kit + gudang",
                   biaya_per_bulan=18000000, durasi_rencana_bulan=18, total=324000000),
        PrelimItem(id=2, project_id=1, rap_version_id=2, uraian="Gaji staf proyek",
                   biaya_per_bulan=45000000, durasi_rencana_bulan=18, total=810000000),
    ])

    # ── vendors ──
    s.add_all([
        Vendor(id=1, name="CV Beton Jaya Sumbawa", jenis="supplier",
               kontak="081234500001", wilayah="Sumbawa Barat", npwp="01.111.222.3-921.000", aktif=True),
        Vendor(id=2, name="PT Baja Utama Lombok", jenis="supplier",
               kontak="081234500002", wilayah="Mataram", npwp="02.222.333.4-922.000", aktif=True),
        Vendor(id=3, name="CV Karya Bekisting Mandiri", jenis="subkon",
               kontak="081234500003", wilayah="Sumbawa Barat", npwp="03.333.444.5-923.000", aktif=True),
        Vendor(id=4, name="CV Waterproof Sejahtera", jenis="subkon",
               kontak="081234500004", wilayah="Mataram", npwp="04.444.555.6-924.000", aktif=True),
    ])

    # ── spks (tanpa SPK-004 yang butuh variations — tabel Fase 3) ──
    s.add_all([
        SPK(id=1, project_id=1, vendor_id=1, rap_item_id=102,
            spk_number="SPK-001/NRC-SBW/2026", jenis="PO",
            work_description="Pengadaan Beton Ready Mix K-300 Lt.2",
            contract_value=477405000, total_additions=0, total_reductions=0,
            retention_pct=0, tanggal_terbit=d("2026-04-08"), status="aktif",
            alokasi_biaya="rap_item"),
        SPK(id=2, project_id=1, vendor_id=3, rap_item_id=106,
            spk_number="SPK-002/NRC-SBW/2026", jenis="SPK",
            work_description="Subkon Bekisting Kolom & Balok Lt.2",
            contract_value=300000000, total_additions=15000000, total_reductions=0,
            retention_pct=5, tanggal_terbit=d("2026-04-22"), status="aktif",
            alokasi_biaya="rap_item"),
        SPK(id=3, project_id=1, vendor_id=3, rap_item_id=None, prelim_item_id=1,
            spk_number="SPK-003/NRC-SBW/2026", jenis="PO",
            work_description="Sewa pagar proyek & rambu K3 sementara",
            contract_value=12000000, tanggal_terbit=d("2026-03-10"), status="selesai",
            alokasi_biaya="prelim"),
        SPK(id=5, project_id=1, vendor_id=3, rap_item_id=None,
            spk_number="SPK-005/NRC-SBW/2026", jenis="PO",
            work_description="Perbaikan bekisting retak akibat kesalahan pemasangan",
            contract_value=6500000, tanggal_terbit=d("2026-06-20"), status="aktif",
            alokasi_biaya="rework"),
    ])

    # ── certificates + payments ──
    s.add_all([
        Certificate(id=1, spk_id=1, nomor="1", periode="2026-05", tanggal=d("2026-05-28"),
                    nilai_tersertifikasi=477405000, progress_factor=1.0, source="manual"),
        Certificate(id=2, spk_id=2, nomor="1", periode="2026-06", tanggal=d("2026-06-25"),
                    nilai_tersertifikasi=189000000, progress_factor=0.6, source="manual"),
    ])
    s.add_all([
        Payment(id=1, spk_id=1, certificate_id=1, amount=477405000, date=d("2026-06-05"), is_dp=False),
        Payment(id=2, spk_id=2, certificate_id=None, amount=30000000, date=d("2026-04-25"), is_dp=True),
        Payment(id=3, spk_id=2, certificate_id=2, amount=149550000, date=d("2026-07-02"), is_dp=False),
    ])

    # ── procurement_requests + price_comparisons (Fase 3) ──
    s.add_all([
        ProcurementRequest(id=1, project_id=1, rap_item_id=102, nomor="PR-2026-001",
                           tanggal_ajukan=d("2026-04-02"), nilai_ajukan=477405000,
                           vendor_terpilih_id=1, status="terbit"),
        ProcurementRequest(id=2, project_id=1, rap_item_id=106, nomor="PR-2026-002",
                           tanggal_ajukan=d("2026-04-15"), nilai_ajukan=300000000,
                           vendor_terpilih_id=3, status="terbit"),
    ])
    s.add_all([
        PriceComparison(id=1, procurement_request_id=1, vendor_id=1, harga=1030000,
                        lingkup_termasuk="Material + antar lokasi", lingkup_tidak_termasuk="Pompa beton",
                        terpilih=True, alasan_tidak_dipilih=""),
        PriceComparison(id=2, procurement_request_id=1, vendor_id=99, harga=995000,
                        lingkup_termasuk="Material saja",
                        lingkup_tidak_termasuk="Antar lokasi, pompa beton",
                        terpilih=False,
                        alasan_tidak_dipilih="Lebih murah tapi tidak termasuk ongkos antar — total efektif lebih mahal dari V-001"),
        PriceComparison(id=3, procurement_request_id=2, vendor_id=3, harga=300000000,
                        lingkup_termasuk="Material + upah + alat bantu",
                        lingkup_tidak_termasuk="Scaffolding", terpilih=True, alasan_tidak_dipilih=""),
    ])

    # ── SPK-004 (variation — tabel variations sudah ada di Fase 3) ──
    s.add(SPK(id=4, project_id=1, vendor_id=4, rap_item_id=None, variation_id=1,
              spk_number="SPK-004/NRC-SBW/2026", jenis="PO",
              work_description="Waterproofing tambahan area talang (CCO-01)",
              contract_value=28000000, tanggal_terbit=d("2026-06-05"), status="aktif",
              alokasi_biaya="variation"))

    # ── spk_status_logs (Fase 3) — lead time SPK-001 6 hari, SPK-002 21 hari ──
    s.add_all([
        SpkStatusLog(id=1, spk_id=1, status="diajukan", timestamp=dt("2026-04-02T09:00:00"), user="Brahma"),
        SpkStatusLog(id=2, spk_id=1, status="review_pusat", timestamp=dt("2026-04-03T10:00:00"), user="system"),
        SpkStatusLog(id=3, spk_id=1, status="terbit", timestamp=dt("2026-04-08T14:00:00"), user="Pusat"),
        SpkStatusLog(id=4, spk_id=2, status="diajukan", timestamp=dt("2026-04-15T09:00:00"), user="Brahma"),
        SpkStatusLog(id=5, spk_id=2, status="review_pusat", timestamp=dt("2026-04-16T09:00:00"), user="system"),
        SpkStatusLog(id=6, spk_id=2, status="terbit", timestamp=dt("2026-05-06T11:00:00"), user="Pusat"),
    ])

    # ── Vendor 2 (PT Baja Utama Lombok) dipakai di proyek 1 DAN proyek 2 — uji lintas proyek ──
    s.add_all([
        SPK(id=101, project_id=1, vendor_id=2, rap_item_id=103,
            spk_number="SPK-006/NRC-SBW/2026", jenis="PO",
            work_description="Pengadaan Besi Ulir D16 tambahan",
            contract_value=120000000, tanggal_terbit=d("2026-05-15"), status="aktif",
            alokasi_biaya="rap_item"),
        SPK(id=201, project_id=2, vendor_id=2,
            spk_number="SPK-001/RUKO-MTR/2026", jenis="PO",
            work_description="Pengadaan besi beton struktur ruko",
            contract_value=350000000, tanggal_terbit=d("2026-06-10"), status="aktif",
            alokasi_biaya="rap_item"),
    ])
    s.add_all([
        SpkStatusLog(id=7, spk_id=101, status="diajukan", timestamp=dt("2026-05-05T09:00:00"), user="Brahma"),
        SpkStatusLog(id=8, spk_id=101, status="terbit", timestamp=dt("2026-05-15T09:00:00"), user="Pusat"),
        SpkStatusLog(id=9, spk_id=201, status="diajukan", timestamp=dt("2026-05-20T09:00:00"), user="Brahma"),
        SpkStatusLog(id=10, spk_id=201, status="terbit", timestamp=dt("2026-06-10T09:00:00"), user="Pusat"),
    ])

    # ── variations (Fase 3) ──
    s.add_all([
        Variation(id=1, project_id=1, nomor="VAR-001", rap_item_id=107,
                  sumber="revisi_gambar", tanggal_peristiwa=d("2026-05-20"),
                  tanggal_notice=d("2026-05-20"), batas_notice=d("2026-06-03"),
                  uraian="Penambahan waterproofing area talang sesuai revisi gambar Ars-14",
                  estimasi_biaya=28000000, nilai_klaim_value=28000000,
                  dampak_waktu_hari=0, status_entitlement="disetujui", cco_ref="CCO-01"),
        Variation(id=2, project_id=1, nomor="VAR-002", rap_item_id=None,
                  sumber="delay_owner", tanggal_peristiwa=d("2026-06-10"),
                  tanggal_notice=d("2026-06-11"), batas_notice=d("2026-06-24"),
                  uraian="Keterlambatan approval shop drawing MEP oleh MK",
                  estimasi_biaya=90000000, nilai_klaim_value=None,
                  dampak_waktu_hari=30, status_entitlement="diajukan", cco_ref=None),
        Variation(id=3, project_id=1, nomor="VAR-003", rap_item_id=103,
                  sumber="instruksi", tanggal_peristiwa=d("2026-07-25"),
                  tanggal_notice=d("2026-07-26"), batas_notice=d("2026-08-02"),
                  uraian="Instruksi tambah besi D16 area balkon (belum ada gambar resmi)",
                  estimasi_biaya=15000000, nilai_klaim_value=None,
                  dampak_waktu_hari=0, status_entitlement="notice_terkirim", cco_ref=None,
                  catatan="Batas notice 2026-08-02 — uji alert H-3 jika cutoff CVR ~2026-07-30"),
        Variation(id=4, project_id=1, nomor=None, rap_item_id=None,
                  sumber="revisi_spek", tanggal_peristiwa=d("2026-07-15"),
                  tanggal_notice=None, batas_notice=None,
                  uraian="Kemungkinan perubahan spek keramik toilet — belum ada instruksi resmi",
                  estimasi_biaya=22000000, nilai_klaim_value=None,
                  dampak_waktu_hari=None, status_entitlement="anticipated", cco_ref=None),
        Variation(id=5, project_id=1, nomor="VAR-005", rap_item_id=106,
                  sumber="instruksi", tanggal_peristiwa=d("2026-06-15"),
                  tanggal_notice=d("2026-06-16"), batas_notice=d("2026-06-30"),
                  uraian="Klaim tambahan biaya scaffolding oleh subkon bekisting — ditolak owner",
                  estimasi_biaya=18000000, nilai_klaim_value=18000000,
                  dampak_waktu_hari=0, status_entitlement="disputed", cco_ref=None,
                  catatan="Tetap masuk cost di CVR meski disputed — lihat metode §3 & §7"),
    ])

    # ── accruals + cvr (Fase 4) — cvr_lines seeded sebagai snapshot manual dummy ──
    s.add_all([
        Accrual(id=1, project_id=1, rap_item_id=106, spk_id=2, periode="2026-07",
                nilai_estimasi=45000000,
                dasar="Opname lapangan visual — bekisting lantai 3 ~80% terpasang, belum diopname resmi",
                dibuat_oleh="Brahma", tanggal=d("2026-07-30")),
    ])
    s.add_all([
        CvrPeriod(id=1, project_id=1, periode="2026-06", cutoff_date=d("2026-06-30"),
                  status="final", disusun_oleh="Brahma", tanggal_final=d("2026-07-03")),
        CvrPeriod(id=2, project_id=1, periode="2026-07", cutoff_date=d("2026-07-31"),
                  status="final", disusun_oleh="Brahma", tanggal_final=d("2026-08-03")),
    ])
    s.add_all([
        CvrLine(cvr_period_id=1, rap_item_id=102,
                value_certified=477405000, value_internal=477405000,
                cost_actual=477405000, cost_accrual=0, cost_committed_outstanding=0,
                forecast_cost_to_complete=0, metode_ctc="sisa_lingkup",
                forecast_final_cost=477405000, forecast_final_value=477405000),
        CvrLine(cvr_period_id=1, rap_item_id=106,
                value_certified=189000000, value_internal=189000000,
                cost_actual=149550000, cost_accrual=30000000, cost_committed_outstanding=120450000,
                forecast_cost_to_complete=120450000, metode_ctc="sisa_lingkup",
                forecast_final_cost=300000000, forecast_final_value=300000000),
        CvrLine(cvr_period_id=2, rap_item_id=106,
                value_certified=189000000, value_internal=189000000,
                cost_actual=149550000, cost_accrual=45000000, cost_committed_outstanding=105450000,
                forecast_cost_to_complete=105450000, metode_ctc="bottom_up",
                forecast_final_cost=315000000, forecast_final_value=315000000,
                catatan="Metode CTC diubah ke bottom_up — subkon bekisting mulai telat, forecast naik 15jt dari periode lalu"),
    ])
    s.add_all([
        CvrCommentary(cvr_period_id=1, penyusun="Brahma",
                      teks="Item 3.3.1 (bekisting): SPK 300jt vs RAP 288jt, buying loss 12jt. Progress 60%, on track. VAR-001 disetujui, tidak berdampak margin signifikan."),
        CvrCommentary(cvr_period_id=2, penyusun="Brahma",
                      teks="Item 3.3.1: forecast final cost naik dari 300jt ke 315jt. Sebab: subkon mulai lambat, metode CTC dialihkan ke bottom-up bersama lapangan. VAR-005 (klaim scaffolding, disputed) tetap dimasukkan sebagai cost meski ditolak owner. Tindakan: rapat evaluasi kinerja subkon minggu depan."),
    ])

    s.commit()
    print("Seed dummy selesai →", TEST_DB)
    print(f"  projects={s.query(Project).count()} boq={s.query(BOQItem).count()} "
          f"versions={s.query(RapVersion).count()} items={s.query(RapItem).count()} "
          f"risks={s.query(RiskAllowance).count()} prelims={s.query(PrelimItem).count()}")
    print(f"  vendors={s.query(Vendor).count()} spks={s.query(SPK).count()} "
          f"certs={s.query(Certificate).count()} payments={s.query(Payment).count()}")
    print(f"  procurement={s.query(ProcurementRequest).count()} comparisons={s.query(PriceComparison).count()} "
          f"status_logs={s.query(SpkStatusLog).count()} variations={s.query(Variation).count()}")
    print(f"  accruals={s.query(Accrual).count()} cvr_periods={s.query(CvrPeriod).count()} "
          f"cvr_lines={s.query(CvrLine).count()} cvr_commentaries={s.query(CvrCommentary).count()}")


if __name__ == "__main__":
    main()
