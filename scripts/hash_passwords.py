"""
Migrasi password plaintext di config.py → hash werkzeug.

Jalankan dari direktori proyek:
    venv/bin/python scripts/hash_passwords.py

- Membaca config.py, menemukan nilai password di dict USERS
- Menggantinya dengan generate_password_hash() (default scrypt)
- Menulis ulang config.py (backup dulu ke config.py.bak)
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")


def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"config.py tidak ditemukan: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        src = f.read()

    # Backup
    backup = CONFIG_PATH + ".bak"
    with open(backup, "w") as f:
        f.write(src)
    print(f"Backup config lama → {backup}")

    # Ganti tiap nilai "password": "..." di dict USERS
    pattern = re.compile(r'("password"\s*:\s*")([^"]*)(")')

    def repl(m):
        plain = m.group(2)
        if not plain:
            return m.group(0)
        if plain.startswith(("scrypt:", "pbkdf2:", "sha256:")):
            return m.group(0)  # sudah hash, skip
        hashed = generate_password_hash(plain)
        print(f"  Hash password: {plain!r} → {hashed[:30]}...")
        return f'{m.group(1)}{hashed}{m.group(3)}'

    new_src, n = pattern.subn(repl, src)

    if n == 0:
        print("Tidak ada password plaintext yang ditemukan — tidak ada yang diubah.")
        sys.exit(0)

    with open(CONFIG_PATH, "w") as f:
        f.write(new_src)

    print(f"Migrasi selesai: {n} password di-hash.")
    print("Verifikasi: login pakai password lama harus tetap berhasil (check_password_hash).")


if __name__ == "__main__":
    main()
