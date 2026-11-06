"""Pembatalan proses panjang (Tarik Chat, cek WhatsApp, Generate) lewat tombol Stop."""


class Cancelled(Exception):
    """Proses dihentikan user lewat tombol Stop."""


def check(should_stop):
    """Lempar Cancelled kalau tombol Stop sudah ditekan."""
    if should_stop and should_stop():
        raise Cancelled()
