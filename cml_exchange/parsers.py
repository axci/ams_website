"""Разбор файлов каталога (import.xml) и предложений (offers.xml) из 1С.

Файлы читаются потоково (iterparse), поэтому каталог на десятки тысяч товаров
не занимает много памяти. Пространства имён XML игнорируются, так что
подходят версии CommerceML 2.03–2.10.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

OFFERS_ROOTS = ("ПакетПредложений", "ИзмененияПакетаПредложений")


# --- помощники для XML ------------------------------------------------------

def local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def children(el, name: str) -> list:
    if el is None:
        return []
    return [c for c in el if local(c.tag) == name]


def child(el, name: str):
    found = children(el, name)
    return found[0] if found else None


def text(el, name: str, default: str = "") -> str:
    c = child(el, name)
    if c is None or c.text is None:
        return default
    return c.text.strip()


def to_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    cleaned = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _is_deleted(el) -> bool:
    return (
        el.get("Статус") == "Удален"
        or text(el, "Статус") == "Удален"
        or text(el, "ПометкаУдаления").lower() == "true"
    )


# --- данные, которые получает обработчик ------------------------------------

@dataclass
class Group:
    """Группа номенклатуры (категория)."""
    id: str
    name: str
    parent_id: Optional[str] = None
    deleted: bool = False


@dataclass
class PropertyDef:
    id: str
    name: str
    value_type: str = ""
    values: dict = field(default_factory=dict)  # ИдЗначения -> текст


@dataclass
class Product:
    """Товар из import.xml. Цен и остатков здесь нет — они в offers.xml."""
    id: str                     # Ид товара в 1С (GUID) — храните его у себя
    name: str
    sku: str = ""               # Артикул
    barcode: str = ""
    description: str = ""
    unit: str = ""              # «шт», «кг» и т. п.
    group_ids: list = field(default_factory=list)
    images: list = field(default_factory=list)       # относительные пути файлов
    properties: dict = field(default_factory=dict)   # {"Цвет": "Красный"}
    requisites: dict = field(default_factory=dict)   # {"Вес": "0.5", "ВидНоменклатуры": "Товар"}
    deleted: bool = False


@dataclass
class PriceType:
    id: str
    name: str
    currency: str = ""


@dataclass
class Price:
    type_id: str
    type_name: str
    value: Decimal
    currency: str = ""
    unit: str = ""


@dataclass
class Offer:
    """Предложение из offers.xml: цены и остатки товара или его характеристики."""
    id: str                         # как в 1С: "<товар>" или "<товар>#<характеристика>"
    product_id: str
    characteristic_id: Optional[str] = None
    name: str = ""
    sku: str = ""
    characteristics: dict = field(default_factory=dict)  # {"Размер": "XL"}
    prices: list = field(default_factory=list)
    quantity: Optional[Decimal] = None  # None — остаток в этом файле не передавался
    stocks: dict = field(default_factory=dict)            # ИдСклада -> количество
    deleted: bool = False

    def price(self, type_name: Optional[str] = None) -> Optional[Decimal]:
        """Цена нужного вида («Розничная»). Без аргумента — первая из переданных."""
        if not self.prices:
            return None
        if type_name:
            wanted = type_name.strip().lower()
            for p in self.prices:
                if p.type_name.strip().lower() == wanted:
                    return p.value
            return None
        return self.prices[0].value


@dataclass
class ImportResult:
    finished: bool
    position: int = 0
    groups: int = 0
    products: int = 0
    offers: int = 0

    def summary(self) -> str:
        parts = []
        if self.groups:
            parts.append(f"групп: {self.groups}")
        if self.products:
            parts.append(f"товаров: {self.products}")
        if self.offers:
            parts.append(f"предложений: {self.offers}")
        return "Обработано " + (", ".join(parts) if parts else "0 записей")


# --- разбор отдельных элементов -------------------------------------------

def parse_groups(el, parent_id=None, out=None) -> list:
    out = [] if out is None else out
    for g in children(el, "Группа"):
        gid = text(g, "Ид")
        out.append(Group(id=gid, name=text(g, "Наименование"), parent_id=parent_id,
                         deleted=_is_deleted(g)))
        parse_groups(child(g, "Группы"), gid, out)
    return out


def parse_properties(el) -> dict:
    result = {}
    for p in children(el, "Свойство"):
        pid = text(p, "Ид")
        values = {}
        for v in children(child(p, "ВариантыЗначений"), "Справочник"):
            values[text(v, "ИдЗначения")] = text(v, "Значение")
        result[pid] = PropertyDef(id=pid, name=text(p, "Наименование"),
                                  value_type=text(p, "ТипЗначений"), values=values)
    return result


def parse_product(el, props: dict) -> Product:
    unit_el = child(el, "БазоваяЕдиница")
    unit = ""
    if unit_el is not None:
        unit = (unit_el.text or "").strip() or unit_el.get("НаименованиеКраткое", "")

    properties = {}
    for pv in children(child(el, "ЗначенияСвойств"), "ЗначенияСвойства"):
        prop_id = text(pv, "Ид")
        definition = props.get(prop_id)
        raw_values = [(v.text or "").strip() for v in children(pv, "Значение")]
        values = [definition.values.get(v, v) if definition else v for v in raw_values if v]
        if values:
            properties[definition.name if definition else prop_id] = ", ".join(values)

    requisites = {}
    for r in children(child(el, "ЗначенияРеквизитов"), "ЗначениеРеквизита"):
        requisites[text(r, "Наименование")] = text(r, "Значение")

    return Product(
        id=text(el, "Ид"),
        name=text(el, "Наименование"),
        sku=text(el, "Артикул"),
        barcode=text(el, "Штрихкод"),
        description=text(el, "Описание"),
        unit=unit,
        group_ids=[(g.text or "").strip() for g in children(child(el, "Группы"), "Ид")],
        images=[(c.text or "").strip() for c in children(el, "Картинка") if (c.text or "").strip()],
        properties=properties,
        requisites=requisites,
        deleted=_is_deleted(el),
    )


def parse_offer(el, price_types: dict) -> Offer:
    offer_id = text(el, "Ид")
    product_id, _, characteristic_id = offer_id.partition("#")

    characteristics = {}
    for c in children(child(el, "ХарактеристикиТовара"), "ХарактеристикаТовара"):
        characteristics[text(c, "Наименование")] = text(c, "Значение")

    prices = []
    for c in children(child(el, "Цены"), "Цена"):
        value = to_decimal(text(c, "ЦенаЗаЕдиницу"))
        if value is None:
            continue
        type_id = text(c, "ИдТипаЦены")
        pt = price_types.get(type_id)
        prices.append(Price(
            type_id=type_id,
            type_name=pt.name if pt else text(c, "Представление"),
            value=value,
            currency=text(c, "Валюта") or (pt.currency if pt else ""),
            unit=text(c, "Единица"),
        ))

    quantity = to_decimal(text(el, "Количество"))
    stocks = {}
    for s in children(el, "Склад"):                     # CommerceML 2.03–2.07
        qty = to_decimal(s.get("КоличествоНаСкладе"))
        if s.get("ИдСклада") and qty is not None:
            stocks[s.get("ИдСклада")] = qty
    for rest in children(child(el, "Остатки"), "Остаток"):  # CommerceML 2.08+
        warehouse = child(rest, "Склад")
        if warehouse is not None:
            qty = to_decimal(text(warehouse, "Количество"))
            if qty is not None:
                stocks[text(warehouse, "Ид")] = qty
        else:
            qty = to_decimal(text(rest, "Количество"))
            if qty is not None:
                quantity = qty
    if quantity is None and stocks:
        quantity = sum(stocks.values(), Decimal(0))

    return Offer(
        id=offer_id,
        product_id=product_id,
        characteristic_id=characteristic_id or None,
        name=text(el, "Наименование"),
        sku=text(el, "Артикул"),
        characteristics=characteristics,
        prices=prices,
        quantity=quantity,
        stocks=stocks,
        deleted=_is_deleted(el),
    )


def _flag(value) -> Optional[bool]:
    if value is None:
        return None
    return str(value).strip().lower() == "true"


# --- импорт файла ---------------------------------------------------------

def import_file(path: Path, handler, start: int = 0, deadline: Optional[float] = None) -> ImportResult:
    """Разбирает файл и вызывает методы обработчика.

    start — сколько товаров/предложений уже обработано в прошлых запросах
    (их пропускаем). deadline — момент time.monotonic(), после которого
    прерываемся и возвращаем finished=False.
    """
    result = ImportResult(finished=True)
    tags, elements = [], []
    props, price_types, warehouses = {}, {}, {}
    only_changes = {"catalog": None, "offers": None}
    started = {"catalog": False, "offers": False}
    index = 0
    resumed = start > 0

    def begin(kind):
        if started[kind]:
            return
        started[kind] = True
        if resumed:
            return
        if kind == "catalog":
            handler.on_catalog_start(bool(only_changes["catalog"]))
        else:
            handler.on_offers_start(bool(only_changes["offers"]),
                                    list(price_types.values()), dict(warehouses))

    with open(path, "rb") as fh:
        for event, el in ET.iterparse(fh, events=("start", "end")):
            tag = local(el.tag)
            if event == "start":
                tags.append(tag)
                elements.append(el)
                if tag == "Каталог":
                    only_changes["catalog"] = _flag(el.get("СодержитТолькоИзменения"))
                elif tag in OFFERS_ROOTS:
                    flag = _flag(el.get("СодержитТолькоИзменения"))
                    only_changes["offers"] = True if tag == "ИзмененияПакетаПредложений" else flag
                continue

            parent = tags[-2] if len(tags) > 1 else None
            grand = tags[-3] if len(tags) > 2 else None
            release = False
            stop = False

            if tag == "Классификатор":
                groups = parse_groups(child(el, "Группы"))
                props.update(parse_properties(child(el, "Свойства")))
                result.groups = len(groups)
                if groups and not resumed:
                    handler.on_groups(groups)
                release = True
            elif tag == "СодержитТолькоИзменения" and parent in ("Каталог",) + OFFERS_ROOTS:
                key = "catalog" if parent == "Каталог" else "offers"
                only_changes[key] = _flag(el.text)
            elif tag == "ТипыЦен" and parent in OFFERS_ROOTS:
                for pt in children(el, "ТипЦены"):
                    ptype = PriceType(text(pt, "Ид"), text(pt, "Наименование"), text(pt, "Валюта"))
                    price_types[ptype.id] = ptype
            elif tag == "Склады" and parent in OFFERS_ROOTS:
                for w in children(el, "Склад"):
                    warehouses[text(w, "Ид")] = text(w, "Наименование")
            elif tag == "Товар" and parent == "Товары" and grand == "Каталог":
                begin("catalog")
                if index >= start:
                    handler.on_product(parse_product(el, props))
                    result.products += 1
                    stop = deadline is not None and time.monotonic() >= deadline
                index += 1
                release = True
            elif tag == "Предложение" and parent == "Предложения" and grand in OFFERS_ROOTS:
                begin("offers")
                if index >= start:
                    handler.on_offer(parse_offer(el, price_types))
                    result.offers += 1
                    stop = deadline is not None and time.monotonic() >= deadline
                index += 1
                release = True
            elif tag == "Каталог":
                begin("catalog")
                handler.on_catalog_end(bool(only_changes["catalog"]))
            elif tag in OFFERS_ROOTS:
                begin("offers")
                handler.on_offers_end(bool(only_changes["offers"]))

            tags.pop()
            elements.pop()
            if release:
                el.clear()
                if elements:
                    elements[-1].remove(el)
            if stop:
                result.finished = False
                result.position = index
                return result

    result.position = index
    return result
