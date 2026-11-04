; Installer HRGA WA Report (Inno Setup 6).
; Build: jalankan build.ps1, yang memanggil ISCC.exe dengan /DAppVersion=<versi>.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "HRGA WA Report"
#define AppExe "HRGA WA Report.exe"

[Setup]
AppId={{6C2F4B1E-8E0D-4C55-9A57-2B7F0C3E9A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=IT Support PT Tradecorp Indonesia
AppCopyright=IT Support PT Tradecorp Indonesia
VersionInfoCompany=IT Support PT Tradecorp Indonesia
VersionInfoDescription={#AppName} Setup
VersionInfoVersion={#AppVersion}
; Dipasang per user tanpa hak admin, supaya update otomatis bisa menimpa .exe.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
; Halaman Selamat Datang menampilkan gambar wizard bertema Tradecorp.
DisableWelcomePage=no
DisableDirPage=yes
OutputDir=..\dist
OutputBaseFilename=HRGA-WA-Report-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard-1x.bmp,wizard-2x.bmp
WizardSmallImageFile=small-1x.bmp,small-2x.bmp
WizardImageStretch=no
WizardImageBackColor=$FFFFFF
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Messages]
ButtonBack=< Kembali
ButtonNext=Lanjut >
ButtonInstall=Pasang
ButtonCancel=Batal
ButtonFinish=Selesai
WizardSelectTasks=Pilih Opsi Tambahan
SelectTasksDesc=Opsi tambahan apa yang ingin dipakai?
SelectTasksLabel2=Pilih opsi tambahan untuk [name], lalu klik Lanjut.
WizardReady=Siap Memasang
ReadyLabel1=[name] siap dipasang di laptop ini.
ReadyLabel2a=Klik Pasang untuk mulai memasang.
WizardInstalling=Sedang Memasang
InstallingLabel=Tunggu sebentar, [name] sedang dipasang.
ClickFinish=Klik Selesai untuk menutup installer.
ClickNext=Klik Lanjut untuk melanjutkan, atau Batal untuk keluar.
ExitSetupTitle=Batalkan Instalasi
ExitSetupMessage=Instalasi belum selesai. Yakin ingin keluar?
WelcomeLabel1=Selamat datang di {#AppName}
WelcomeLabel2=Aplikasi ini menarik chat WhatsApp hari ini dan menyusun draf daily report untuk tim HRGA PT Tradecorp Indonesia.%n%nDibuat oleh IT Support.
FinishedHeadingLabel=Instalasi {#AppName} selesai
FinishedLabel={#AppName} sudah terpasang. Buka aplikasinya, isi nama di Pengaturan, lalu hubungkan WhatsApp.

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Shortcut:"
Name: "autostart"; Description: "Jalankan otomatis saat Windows menyala"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Nama nilai sama dengan core/autostart.py, jadi centang di Pengaturan app ikut sinkron.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Buka {#AppName} sekarang"; Flags: nowait postinstall skipifsilent
