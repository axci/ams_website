"""Заказы: выгрузка с сайта в 1С и приём изменений заказов из 1С."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

from django.utils import timezone

from . import conf
from .parsers import child, children, local, text, to_decimal

DELIVERY_ITEM_ID = "ORDER_DELIVERY"


@dataclass
class Customer:
    id: str                       # постоянный Ид покупателя на сайте, например "user-15"
    name: str                     # как контрагент будет называться в 1С
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    is_company: bool = False
    inn: str = ""
    kpp: str = ""


@dataclass
class OrderItem:
    product_id: str               # Ид товара из 1С; для характеристики — "<товар>#<характеристика>"
    name: str
    quantity: Decimal
    price: Decimal
    total: Optional[Decimal] = None   # по умолчанию цена × количество
    unit: str = "шт"
    unit_code: str = "796"            # код ОКЕИ, 796 — штука
    is_service: bool = False
    code: str = ""                    # Код номенклатуры — для сопоставления

    @property
    def amount(self) -> Decimal:
        if self.total is not None:
            return Decimal(self.total)
        return Decimal(self.price) * Decimal(self.quantity)


@dataclass
class OrderData:
    id: str                       # постоянный Ид заказа на сайте
    number: str
    created: datetime
    customer: Customer
    items: list = field(default_factory=list)
    currency: str = "RUB"
    comment: str = ""
    status: str = ""
    paid: bool = False
    payment_method: str = ""
    delivery_method: str = ""
    delivery_price: Decimal = Decimal(0)
    delivery_address: str = ""
    cancelled: bool = False
    extra: dict = field(default_factory=dict)   # дополнительные реквизиты {"Наименование": "Значение"}

    @property
    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), Decimal(0)) + Decimal(self.delivery_price or 0)


@dataclass
class OrderUpdate:
    """Документ, который 1С прислала на сайт (обычно — изменение заказа)."""
    id: str
    number: str
    date: str = ""
    operation: str = ""
    total: Optional[Decimal] = None
    requisites: dict = field(default_factory=dict)   # {"Проведен": "true", "Статус заказа": "..."}


def _money(value) -> str:
    return f"{Decimal(value or 0):.2f}"


def _qty(value) -> str:
    return format(Decimal(value).normalize(), "f")


def _sub(parent, tag, value=None, **attrs):
    el = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if value is not None:
        el.text = str(value)
    return el


def _requisite(parent, name, value):
    req = _sub(parent, "ЗначениеРеквизита")
    _sub(req, "Наименование", name)
    _sub(req, "Значение", value)


def _local_dt(value: datetime) -> datetime:
    if timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def build_orders_xml(orders: Iterable[OrderData]) -> bytes:
    now = _local_dt(timezone.now())
    root = ET.Element("КоммерческаяИнформация", {
        "ВерсияСхемы": conf.get("SCHEMA_VERSION"),
        "ДатаФормирования": now.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    for order in orders:
        created = _local_dt(order.created)
        doc = _sub(root, "Документ")
        _sub(doc, "Ид", order.id)
        _sub(doc, "Номер", order.number)
        _sub(doc, "Дата", created.strftime("%Y-%m-%d"))
        _sub(doc, "ХозОперация", "Заказ товара")
        _sub(doc, "Роль", "Продавец")
        _sub(doc, "Валюта", order.currency)
        _sub(doc, "Курс", "1")
        _sub(doc, "Сумма", _money(order.total))

        c = order.customer
        agents = _sub(doc, "Контрагенты")
        agent = _sub(agents, "Контрагент")
        _sub(agent, "Ид", c.id)
        _sub(agent, "Наименование", c.name)
        _sub(agent, "Роль", "Покупатель")
        if c.is_company:
            _sub(agent, "ОфициальноеНаименование", c.name)
            if c.inn:
                _sub(agent, "ИНН", c.inn)
            if c.kpp:
                _sub(agent, "КПП", c.kpp)
            if c.address:
                _sub(_sub(agent, "ЮридическийАдрес"), "Представление", c.address)
        else:
            _sub(agent, "ПолноеНаименование", c.name)
            if c.last_name:
                _sub(agent, "Фамилия", c.last_name)
            if c.first_name:
                _sub(agent, "Имя", c.first_name)
            if c.inn:
                _sub(agent, "ИНН", c.inn)
            if c.address:
                _sub(_sub(agent, "АдресРегистрации"), "Представление", c.address)
        if c.email or c.phone:
            contacts = _sub(agent, "Контакты")
            if c.email:
                ct = _sub(contacts, "Контакт")
                _sub(ct, "Тип", "Почта")
                _sub(ct, "Значение", c.email)
            if c.phone:
                ct = _sub(contacts, "Контакт")
                _sub(ct, "Тип", "ТелефонРабочий")
                _sub(ct, "Значение", c.phone)

        _sub(doc, "Время", created.strftime("%H:%M:%S"))
        if order.comment:
            _sub(doc, "Комментарий", order.comment)

        goods = _sub(doc, "Товары")
        items = list(order.items)
        if order.delivery_price:
            items.append(OrderItem(product_id=DELIVERY_ITEM_ID, name="Доставка заказа",
                                   quantity=Decimal(1), price=Decimal(order.delivery_price),
                                   is_service=True))
        for item in items:
            g = _sub(goods, "Товар")
            _sub(g, "Ид", item.product_id)
            if item.code:
                _sub(g, "Код", item.code)
            _sub(g, "Наименование", item.name)
            _sub(g, "БазоваяЕдиница", item.unit, Код=item.unit_code,
                 НаименованиеПолное="Штука" if item.unit_code == "796" else item.unit)
            _sub(g, "ЦенаЗаЕдиницу", _money(item.price))
            _sub(g, "Количество", _qty(item.quantity))
            _sub(g, "Сумма", _money(item.amount))
            reqs = _sub(g, "ЗначенияРеквизитов")
            kind = "Услуга" if item.is_service else "Товар"
            _requisite(reqs, "ВидНоменклатуры", kind)
            _requisite(reqs, "ТипНоменклатуры", kind)

        reqs = _sub(doc, "ЗначенияРеквизитов")
        if order.payment_method:
            _requisite(reqs, "Метод оплаты", order.payment_method)
        _requisite(reqs, "Заказ оплачен", "true" if order.paid else "false")
        if order.delivery_method:
            _requisite(reqs, "Способ доставки", order.delivery_method)
        if order.delivery_address:
            _requisite(reqs, "Адрес доставки", order.delivery_address)
        _requisite(reqs, "Отменен", "true" if order.cancelled else "false")
        if order.status:
            _requisite(reqs, "Статус заказа", order.status)
        for name, value in order.extra.items():
            _requisite(reqs, name, value)

    encoding = conf.get("ORDERS_ENCODING")
    return ET.tostring(root, encoding=encoding, xml_declaration=True)


def parse_order_updates(path: Path) -> list:
    tree = ET.parse(path)
    result = []
    for doc in tree.getroot().iter():
        if local(doc.tag) != "Документ":
            continue
        requisites = {}
        for r in children(child(doc, "ЗначенияРеквизитов"), "ЗначениеРеквизита"):
            requisites[text(r, "Наименование")] = text(r, "Значение")
        result.append(OrderUpdate(
            id=text(doc, "Ид"),
            number=text(doc, "Номер"),
            date=text(doc, "Дата"),
            operation=text(doc, "ХозОперация"),
            total=to_decimal(text(doc, "Сумма")),
            requisites=requisites,
        ))
    return result
