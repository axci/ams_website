"""Обработчик — место, где данные 1С связываются с вашими моделями.

Создайте свой класс-наследник BaseHandler, переопределите нужные методы
и укажите его в CML_EXCHANGE["HANDLER"]. Порядок вызовов при выгрузке каталога:

    import.xml:  on_groups → on_catalog_start → on_product (для каждого товара) → on_catalog_end
    offers.xml:  on_offers_start → on_offer (для каждого предложения) → on_offers_end

Большой файл может обрабатываться за несколько HTTP-запросов (ответ «progress»).
Тогда on_groups/on_*_start вызываются только в первом запросе, а on_*_end — в
последнем, и каждый запрос получает новый экземпляр обработчика. Поэтому не
храните состояние в атрибутах между вызовами — пишите сразу в базу.

Обмен заказами:

    get_orders → (1С загрузила) → on_orders_exported
    on_order_update — когда 1С присылает на сайт изменения заказов
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from django.utils.module_loading import import_string

from . import conf

logger = logging.getLogger("cml_exchange")


class BaseHandler:
    def __init__(self, files_dir: Path, session_started: Optional[datetime] = None):
        #: Папка с файлами текущего сеанса (import.xml, offers.xml, import_files/...)
        self.files_dir = files_dir
        #: Время начала сеанса обмена каталогом (шаг init). Удобно для полной
        #: выгрузки: всё, что не обновилось после этого момента, нет в 1С.
        self.session_started = session_started

    def file_path(self, relative: str) -> Optional[Path]:
        """Абсолютный путь к файлу, присланному 1С (например, к картинке товара)."""
        from .storage import ExchangeError, safe_path
        try:
            path = safe_path("catalog", relative)
        except ExchangeError:
            return None
        return path if path.is_file() else None

    # --- каталог (import.xml) ---
    def on_groups(self, groups: list) -> None:
        """Все группы номенклатуры. Родительская группа идёт раньше дочерних."""

    def on_catalog_start(self, only_changes: bool) -> None:
        """only_changes=False — 1С выгружает весь каталог, True — только изменения."""

    def on_product(self, product) -> None:
        """Создать или обновить товар. product — cml_exchange.parsers.Product."""

    def on_catalog_end(self, only_changes: bool) -> None:
        pass

    # --- предложения (offers.xml) ---
    def on_offers_start(self, only_changes: bool, price_types: list, warehouses: dict) -> None:
        pass

    def on_offer(self, offer) -> None:
        """Обновить цену и остаток. offer — cml_exchange.parsers.Offer.

        offer.quantity is None означает, что остаток в этом файле не передан, —
        тогда его не трогайте. То же с пустым offer.prices.
        """

    def on_offers_end(self, only_changes: bool) -> None:
        pass

    # --- заказы ---
    def get_orders(self) -> Iterable:
        """Вернуть заказы для 1С: список cml_exchange.orders.OrderData.

        Обычно — заказы, которые ещё не выгружались или изменились после выгрузки.
        """
        return []

    def on_orders_exported(self, order_ids: list) -> None:
        """1С подтвердила загрузку заказов с этими Ид — отметьте их как выгруженные."""

    def on_order_update(self, update) -> None:
        """1С прислала изменения заказа. update — cml_exchange.orders.OrderUpdate."""


class LoggingHandler(BaseHandler):
    """Обработчик по умолчанию: ничего не сохраняет, только пишет в лог.

    Подходит, чтобы проверить связь 1С с сайтом до подключения моделей.
    """

    def on_groups(self, groups):
        logger.info("1С: получено групп: %s", len(groups))

    def on_catalog_start(self, only_changes):
        logger.info("1С: начало выгрузки каталога (только изменения: %s)", only_changes)

    def on_product(self, product):
        logger.debug("1С: товар %s «%s»", product.id, product.name)

    def on_catalog_end(self, only_changes):
        logger.info("1С: каталог получен")

    def on_offer(self, offer):
        logger.debug("1С: предложение %s, цена %s, остаток %s", offer.id, offer.price(), offer.quantity)

    def on_offers_end(self, only_changes):
        logger.info("1С: цены и остатки получены")

    def on_order_update(self, update):
        logger.info("1С: изменения заказа %s: %s", update.number, update.requisites)


def load_handler(files_dir: Path, session_started: Optional[datetime] = None) -> BaseHandler:
    handler_class = import_string(conf.get("HANDLER"))
    return handler_class(files_dir=files_dir, session_started=session_started)
