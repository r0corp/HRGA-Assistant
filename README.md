# HRGA WA Report

App Windows untuk tim HRGA: tarik chat WhatsApp hari ini, susun draf daily report tanpa AI dan tanpa biaya, lalu kirim ke grup tim.

![Tampilan utama](docs/screenshot.png)

## Fitur

- **Tarik chat WhatsApp:** semua chat yang aktif di tanggal report (bisa hari ini atau hari sebelumnya), dibaca lewat WhatsApp Web tanpa membuka jendela browser.
- **Tabel chat:** tiap chat ditampilkan dengan jumlah pesan dan rentang jam. Chat pribadi bisa dibatalkan centangnya, atau dimasukkan ke daftar "selalu abaikan".
- **Draf report otomatis:** satu poin per chat, berisi maksimal 3 pesan inti (permintaan, jawaban, dan detail terpenting), hanya dari jam kerja (bawaannya 06:00–17:00).
  - Basa-basi, foto, dan stiker dibuang.
  - Link diringkas jadi nama situsnya.
  - Password, OTP, dan nomor rekening disamarkan.
- **Kirim ke grup:** report dikirim hanya ke grup **GRUP TEAM HRGA**. Selain itu, draf bisa disalin atau disimpan sebagai PDF berkop logo perusahaan.
- **Timeline 5 hari kerja:** menandai hari yang sudah report ke grup dan yang terlewat, dibaca langsung dari isi grup. Report yang dikirim manual juga ikut terhitung.
- **Indikator koneksi WhatsApp:** menunjukkan apakah sesi WhatsApp Web masih tersambung.
- **Bahasa Indonesia / English:** untuk tampilan app dan judul report.
- **Jalan otomatis:** app bisa dibuka otomatis setiap Windows menyala.
- **Update otomatis:** app mengecek rilis baru di GitHub saat dibuka. Bisa juga dicek manual di Pengaturan > Cek update.

![Pengaturan](docs/screenshot-settings.png)

## Instalasi

1. Unduh `HRGA-WA-Report-Setup-<versi>.exe` dari halaman [Releases](https://github.com/r0corp/hrga-wa-report/releases/latest), lalu jalankan.
   - Tidak perlu hak admin; app dipasang per user.
   - App memakai Microsoft Edge bawaan Windows, jadi tidak ada browser tambahan yang dipasang.
2. Buka app, klik **Pengaturan**, lalu isi nama.
3. Klik **Hubungkan WhatsApp** dan scan QR code dari HP (WhatsApp > Perangkat tertaut > Tautkan perangkat).
4. Setiap sore: **Tarik Chat**, lalu **Generate Report**, rapikan kalimatnya, dan **Kirim ke Grup**.

Data tiap laptop (sesi WhatsApp, chat, report, pengaturan) disimpan di `%LOCALAPPDATA%\HRGA WA Report` dan tidak pernah diunggah ke mana pun.

## Catatan

- Membuka chat membuat pesan tertandai dibaca (centang biru).
- Otomatisasi WhatsApp Web tidak diizinkan oleh ketentuan WhatsApp. App ini hanya membaca dengan jeda, tapi risikonya tidak nol.

## Pengembangan

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m pytest -q
venv\Scripts\python app.py
```

### Build dan rilis

1. Naikkan `VERSION` di `core/updater.py`.
2. Jalankan `powershell -ExecutionPolicy Bypass -File build.ps1`. Hasilnya ada di `dist\`:
   - `HRGA WA Report.exe`
   - `HRGA-WA-Report-Setup-<versi>.exe` (perlu [Inno Setup 6](https://jrsoftware.org/isinfo.php))
3. Buat rilis GitHub dengan tag `v<versi>` dan lampirkan kedua file itu. App yang sudah terpasang memakai `.exe` app (bukan installer) untuk update otomatis.

---

Dibuat oleh IT Support.
