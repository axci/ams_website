"""Точка входа для 1С. Один адрес, режим задают параметры type и mode.

Каталог (type=catalog): checkauth → init → file (много раз) → import (по каждому файлу)
Заказы  (type=sale):    checkauth → init → query → success → [file — изменения из 1С]
"""
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import auth, conf, storage
from .handlers import load_handler
from .orders import build_orders_xml, parse_order_updates
from .parsers import import_file
from .storage import ExchangeError

logger = logging.getLogger("cml_exchange")


def _text(*lines, status=200):
    return HttpResponse("\n".join(str(line) for line in lines),
                        content_type="text/plain; charset=utf-8", status=status)


def _success(*lines):
    return _text("success", *lines)


def _failure(message, status=200):
    logger.warning("Обмен с 1С: %s", message)
    return _text("failure", message, status=status)


@csrf_exempt
def exchange(request):
    kind = request.GET.get("type", "")
    mode = request.GET.get("mode", "")
    logger.info("1С → сайт: type=%s mode=%s filename=%s", kind, mode, request.GET.get("filename", ""))
    try:
        if kind not in storage.KINDS:
            return _failure(f"Неподдерживаемый тип обмена: {kind or '(не указан)'}")
        if mode == "checkauth":
            return _checkauth(request)
        if not conf.credentials_configured():
            return _failure("На сайте не заданы CML_EXCHANGE['USERNAME'] и ['PASSWORD']")
        if not auth.is_authorized(request):
            return _failure("Сеанс не авторизован: начните обмен заново (шаг checkauth)")
        if mode == "init":
            return _init(kind)
        if mode == "file":
            return _file(request, kind)
        if mode == "import":
            return _import(request, kind)
        if kind == "sale" and mode == "query":
            return _query()
        if kind == "sale" and mode == "success":
            return _sale_success()
        if mode in ("complete", "deactivate"):   # шаги новых версий протокола
            return _success()
        return _failure(f"Неизвестный режим обмена: {mode or '(не указан)'}")
    except ExchangeError as exc:
        return _failure(str(exc))
    except Exception as exc:  # 1С должна получить понятный текст, а не HTML-страницу 500
        logger.exception("Ошибка обмена с 1С")
        return _failure(f"Ошибка на сайте: {exc.__class__.__name__}: {exc}")


def _checkauth(request):
    if not auth.has_basic_header(request):
        response = _failure("Нужна авторизация: логин и пароль из настройки обмена", status=401)
        response["WWW-Authenticate"] = 'Basic realm="1C exchange", charset="UTF-8"'
        return response
    if not conf.credentials_configured():
        return _failure("На сайте не заданы CML_EXCHANGE['USERNAME'] и ['PASSWORD']")
    if not auth.check_basic(request):
        return _failure("Неверный логин или пароль")
    return _success(auth.COOKIE_NAME, auth.issue_token())


def _init(kind):
    storage.reset(kind)
    if kind == "catalog":
        storage.save_state("catalog", {"session_started": timezone.now().isoformat(), "progress": {}})
    return _text("zip=no", f"file_limit={int(conf.get('FILE_LIMIT'))}")


def _file(request, kind):
    if request.method != "POST":
        return _failure("Файл нужно передавать методом POST")
    filename = request.GET.get("filename", "")
    target = storage.safe_path(kind, filename)
    size = storage.append_request_body(request, target)
    logger.info("1С: получен файл %s (%s байт)", filename, size)
    if kind == "sale" and target.suffix.lower() == ".xml":
        # В классической схеме 1С не вызывает import для заказов — разбираем сразу.
        try:
            _apply_order_updates(target)
        except ET.ParseError:
            logger.info("1С: файл %s пока неполный, ждём продолжения", filename)
    return _success()


def _session_started():
    raw = storage.load_state("catalog").get("session_started")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _import(request, kind):
    filename = request.GET.get("filename", "")
    path = storage.safe_path(kind, filename)
    if not path.is_file():
        return _failure(f"Файл {filename} не найден на сайте — 1С должна сначала его передать")

    if kind == "sale":
        _apply_order_updates(path)
        return _success()

    state = storage.load_state("catalog")
    progress = state.setdefault("progress", {})
    start = int(progress.get(filename, 0))
    limit = float(conf.get("IMPORT_TIME_LIMIT") or 0)
    deadline = time.monotonic() + limit if limit > 0 else None

    handler = load_handler(storage.type_dir("catalog"), _session_started())
    result = import_file(path, handler, start=start, deadline=deadline)

    if result.finished:
        progress.pop(filename, None)
        storage.save_state("catalog", state)
        logger.info("1С: %s обработан. %s", filename, result.summary())
        return _success(f"{filename}: {result.summary()}")

    progress[filename] = result.position
    storage.save_state("catalog", state)
    return _text("progress", f"{filename}: обработано записей {result.position}")


def _apply_order_updates(path):
    handler = load_handler(storage.type_dir("sale"), None)
    for update in parse_order_updates(path):
        handler.on_order_update(update)


def _query():
    handler = load_handler(storage.type_dir("sale"), None)
    orders = list(handler.get_orders())
    xml = build_orders_xml(orders)
    storage.save_state("sale", {"sent": [o.id for o in orders]})
    (storage.type_dir("sale") / "to_1c.xml").write_bytes(xml)   # копия для разбора проблем
    logger.info("1С: отдано заказов: %s", len(orders))
    return HttpResponse(xml, content_type=f"application/xml; charset={conf.get('ORDERS_ENCODING')}")


def _sale_success():
    state = storage.load_state("sale")
    sent = state.pop("sent", [])
    if sent:
        load_handler(storage.type_dir("sale"), None).on_orders_exported(sent)
    storage.save_state("sale", state)
    return _success()
