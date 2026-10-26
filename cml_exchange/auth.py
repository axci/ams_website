"""Авторизация 1С.

1С на шаге checkauth присылает логин и пароль (HTTP Basic). В ответ сайт выдаёт
имя и значение cookie, которое 1С передаёт во всех следующих запросах сеанса.
Значение cookie — подписанный SECRET_KEY токен с отметкой времени, поэтому
хранить сессии на сервере не нужно и всё работает с любым числом воркеров.
"""
import base64
import binascii
import hmac

from django.core import signing

from . import conf

COOKIE_NAME = "cml_token"
_SALT = "cml_exchange.token"


def _decode_basic(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header[:6].lower() == "basic ":
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    for encoding in ("utf-8", "cp1251"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    login, sep, password = decoded.partition(":")
    if not sep:
        return None
    return login, password


def has_basic_header(request) -> bool:
    return bool(request.META.get("HTTP_AUTHORIZATION"))


def check_basic(request) -> bool:
    creds = _decode_basic(request)
    if creds is None or not conf.credentials_configured():
        return False
    login, password = creds
    login_ok = hmac.compare_digest(login.encode(), str(conf.get("USERNAME")).encode())
    password_ok = hmac.compare_digest(password.encode(), str(conf.get("PASSWORD")).encode())
    return login_ok and password_ok


def issue_token() -> str:
    return signing.dumps({"u": conf.get("USERNAME")}, salt=_SALT, compress=False)


def check_token(request) -> bool:
    token = request.COOKIES.get(COOKIE_NAME)
    if not token:
        return False
    try:
        data = signing.loads(token, salt=_SALT, max_age=conf.get("TOKEN_MAX_AGE"))
    except signing.BadSignature:
        return False
    return isinstance(data, dict) and data.get("u") == conf.get("USERNAME")


def is_authorized(request) -> bool:
    """Запрос внутри сеанса: годится cookie из checkauth или логин/пароль."""
    if not conf.credentials_configured():
        return False
    return check_token(request) or check_basic(request)
