"""Настройки приложения. Задаются в settings.py словарём CML_EXCHANGE.

Пример:

    CML_EXCHANGE = {
        "USERNAME": os.environ["CML_USERNAME"],
        "PASSWORD": os.environ["CML_PASSWORD"],
        "HANDLER": "shop.cml_handler.ShopHandler",
        "DIR": BASE_DIR / "var" / "1c_exchange",
    }
"""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS = {
    # Логин и пароль, которые вводятся в 1С в настройке обмена с сайтом.
    "USERNAME": None,
    "PASSWORD": None,
    # Класс, который переносит данные из 1С в ваши модели и отдаёт заказы.
    "HANDLER": "cml_exchange.handlers.LoggingHandler",
    # Папка для файлов обмена. НЕ кладите её внутрь публичного MEDIA_ROOT:
    # там лежат цены, остатки и заказы.
    "DIR": None,
    # Максимальный размер одного запроса с файлом (байт). Должен быть не больше,
    # чем client_max_body_size в nginx.
    "FILE_LIMIT": 50 * 1024 * 1024,
    # Сколько секунд обрабатывать файл за один запрос. Если не успели,
    # сайт отвечает 1С «progress», и 1С повторяет запрос. 0 — без ограничения.
    "IMPORT_TIME_LIMIT": 20,
    # Сколько секунд действует ключ сеанса, выданный 1С при авторизации.
    "TOKEN_MAX_AGE": 24 * 3600,
    # Кодировка XML с заказами для 1С.
    "ORDERS_ENCODING": "utf-8",
    # Версия схемы CommerceML в выгрузке заказов.
    "SCHEMA_VERSION": "2.05",
}


def get(name):
    user_settings = getattr(settings, "CML_EXCHANGE", {}) or {}
    return user_settings.get(name, DEFAULTS[name])


def exchange_dir() -> Path:
    configured = get("DIR")
    if configured:
        return Path(configured)
    base_dir = getattr(settings, "BASE_DIR", None)
    if not base_dir:
        raise ImproperlyConfigured(
            "Укажите CML_EXCHANGE['DIR'] — папку для файлов обмена с 1С."
        )
    return Path(base_dir) / "var" / "1c_exchange"


def credentials_configured() -> bool:
    return bool(get("USERNAME")) and bool(get("PASSWORD"))
