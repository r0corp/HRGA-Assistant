# Server HRGA (PC server + Tailscale Funnel)

Server HRGA menampung report harian seluruh tim HRGA untuk Fena:

- **Tim Android** (tanpa laptop) membuka halaman web lewat Chrome di HP. Mereka mengetik atau mendikte cerita pekerjaan, Claude merapikannya jadi daily report, lalu mereka tekan **Kirim ke Fena**.
- **Tim laptop** memakai app HRGA WA Report seperti biasa. Tombol kirimnya menjadi **Kirim ke Fena** (Pengaturan → Tujuan report).
- **Fena** melihat siapa yang sudah dan belum report di **Rekap Tim**, baik di app laptop maupun di web (menu Rekap Tim).

Server berjalan di dalam app yang sama (exe yang sama), jadi update tetap lewat tombol **Update sekarang**.

## 1. Siapkan PC server (sekali saja)

1. Pasang `HRGA-WA-Report-Setup-x.y.z.exe` di PC server.
2. Buka app, lalu login **Claude** dengan **akun Fena** (klik status Claude di sidebar). Akun ini dipakai untuk merapikan report tim Android.
3. Pengaturan:
   - centang **Jalankan otomatis saat Windows menyala**;
   - centang **Jadikan PC ini server HRGA**;
   - klik **Simpan**.
4. Di Pengaturan sekarang muncul tulisan **Server aktif di 127.0.0.1:8400**.

PC server harus tetap menyala dan user Windows-nya login (app terbuka). Atur Power Options supaya PC tidak sleep.

## 2. Tailscale Funnel (alamat publik HTTPS)

1. Pasang Tailscale dari https://tailscale.com/download/windows, lalu login ke akun Tailscale kantor/IT.
2. Di https://login.tailscale.com/admin:
   - **DNS** → aktifkan **MagicDNS** dan **HTTPS Certificates**.
   - **Access controls** → tambahkan izin Funnel untuk PC server, misalnya:
     ```json
     "nodeAttrs": [
       { "target": ["autogroup:member"], "attr": ["funnel"] }
     ]
     ```
3. (Opsional) Di halaman **Machines**, ganti nama mesin PC server menjadi `hrga-server` supaya alamatnya mudah diingat.
4. Di app server: Pengaturan → **Aktifkan Funnel**. Alamat publik akan tampil, misalnya `https://hrga-server.xxxx.ts.net`.
5. Bagikan alamat itu ke tim:
   - **HP Android:** buka di Chrome → menu ⋮ → **Tambahkan ke layar utama**.
   - **Laptop:** Pengaturan → **Alamat server** → **Login** dengan nama + PIN.

Funnel hanya meneruskan HTTPS ke `127.0.0.1:8400`, jadi PC server tidak membuka port lain ke internet. Untuk mematikan akses publik, jalankan `tailscale funnel reset`, atau matikan **Mode server**.

## 3. Buat PIN tiap orang

Di PC server buka Pengaturan → **Kelola user**:

- Pilih nama → **Buat PIN baru**. PIN 6 angka hanya tampil sekali; berikan langsung ke orangnya, jangan lewat grup.
- **Cabut login** untuk keluar paksa dari semua perangkat orang itu, misalnya kalau HP hilang.
- **Tambah** atau **Hapus** untuk anggota baru atau yang keluar.
- Fena dan Rohman (★) adalah admin: bisa membuka Rekap Tim.

## Keamanan

- PIN disimpan sebagai hash PBKDF2, bukan teks asli.
- Salah PIN 5 kali membuat akun terkunci 15 menit. Percobaan berulang dari satu alamat juga diblokir.
- Login tersimpan 30 hari di HP/laptop, lalu harus login ulang. **Cabut login** langsung memutus sesi.
- Password, OTP, dan nomor rekening di cerita/report disamarkan sebelum dikirim ke Claude dan disimpan.
- Log login dan pengiriman ada di `%LOCALAPPDATA%\HRGA WA Report\server\audit.log`.
- Data server (user, sesi, report) ada di `%LOCALAPPDATA%\HRGA WA Report\server\`. Ikutkan folder ini dalam backup.
