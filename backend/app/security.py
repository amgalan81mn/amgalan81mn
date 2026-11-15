"""Токен, SMS код, файл шифрлэлт, оролтын хэлбэр шалгах."""

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet

from .config import get_settings

_PHONE = re.compile(r"^(?:\+?976)?(\d{8})$")
_REGISTER = re.compile(r"^[А-ЯЁӨҮ]{2}\d{8}$")
_PLATE = re.compile(r"^\d{4}[А-ЯЁӨҮ]{2,3}$")


def normalize_phone(raw: str) -> str:
    m = _PHONE.match(re.sub(r"[\s-]", "", raw))
    if not m:
        raise ValueError("Утасны дугаар 8 оронтой байх ёстой")
    return "+976" + m.group(1)


def normalize_register_no(raw: str) -> str:
    value = re.sub(r"\s", "", raw).upper()
    if not _REGISTER.match(value):
        raise ValueError("Регистрийн дугаар 2 кирилл үсэг, 8 цифрээс бүрдэнэ")
    return value


def normalize_plate(raw: str) -> str:
    value = re.sub(r"[\s-]", "", raw).upper()
    if not _PLATE.match(value):
        raise ValueError("Улсын дугаар 4 цифр, 2-3 кирилл үсгээс бүрдэнэ (жишээ: 1234УБА)")
    return value


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def create_token(user_id: str) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)
    return jwt.encode({"sub": user_id, "exp": exp}, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> str | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None


def _fernet() -> Fernet:
    s = get_settings()
    key = s.file_encryption_key
    if not key:  # зөвхөн туршилтад: жинхэнэ орчинд UNAA_FILE_ENCRYPTION_KEY заавал тавина
        key = base64.urlsafe_b64encode(hashlib.sha256(s.jwt_secret.encode()).digest()).decode()
    return Fernet(key)


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    return _fernet().decrypt(data)
