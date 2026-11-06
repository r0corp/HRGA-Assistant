import re


MASK = "[disamarkan]"

# Kata setelah "password", "otp", "pin", dst.
AFTER_KEYWORD_RE = re.compile(
    r"(?i)\b(pass(?:word|wd)?|pw|sandi|kata sandi|otp|pin|kode)\b(\s*[:=]?\s*)(\S+)"
)

# Pesan yang isinya hanya angka 4-8 digit (OTP / PIN yang dikirim sendirian).
ONLY_CODE_RE = re.compile(r"^\s*\d{4,8}\s*$")

# Nomor rekening / kartu: 10-16 digit berurutan. Nomor HP Indonesia (08..., 62..., +62...)
# tidak disamarkan: kontak yang tidak tersimpan tetap bagian dari pekerjaan.
ACCOUNT_RE = re.compile(r"(?<!\+)\b(?!08\d{8,11}\b)(?!628\d{7,11}\b)\d{10,16}\b")

# Token campuran huruf+angka (pola password), tanpa @ / . supaya email,
# link, dan nama file tidak ikut tersamarkan.
SECRET_TOKEN_RE = re.compile(r"(?<![\w@./-])(?=[^\s]*[A-Za-z])(?=[^\s]*\d)[^\s@./]{6,32}(?![\w@./-])")


def redact(text):
    if not text:
        return text

    if ONLY_CODE_RE.match(text):
        return MASK

    text = AFTER_KEYWORD_RE.sub(lambda m: m.group(1) + m.group(2) + MASK, text)
    text = ACCOUNT_RE.sub(MASK, text)
    text = SECRET_TOKEN_RE.sub(MASK, text)

    return text
