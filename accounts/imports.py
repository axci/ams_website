"""Import / update Users from an Excel file (e.g. a debt export from 1C)."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import openpyxl
from django.contrib.auth import get_user_model

User = get_user_model()

# Normalised header -> User field. Only "code" is required.
COLUMN_ALIASES = {
    "контрагент.код": "code",
    "код": "code",
    "контрагент": "company_name",
    "контрагент.инн": "inn",
    "инн": "inn",
    "контрагент.кпп": "kpp",
    "кпп": "kpp",
    "контрагент.юр. адрес": "address",
    "контрагент.юр.адрес": "address",
    "адрес": "address",
    "конечный остаток": "debt",
    "задолженность": "debt",
}


@dataclass
class UserImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)


def _norm(value):
    return str(value).strip().lower() if value is not None else ""


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decimal(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    s = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def import_users(file):
    result = UserImportResult()
    ws = openpyxl.load_workbook(file, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        result.errors.append((1, "Пустой файл."))
        return result

    colmap = {}
    for idx, h in enumerate(header):
        field_name = COLUMN_ALIASES.get(_norm(h))
        if field_name and field_name not in colmap.values():
            colmap[idx] = field_name
    if "code" not in colmap.values():
        result.errors.append((1, "Не найден обязательный столбец «Контрагент.Код»."))
        return result

    for rownum, row in enumerate(rows, start=2):
        values = {colmap[i]: row[i] for i in colmap if i < len(row)}
        code = _text(values.get("code"))
        if not code:
            result.skipped += 1
            continue
        try:
            user = User.objects.filter(code=code).first()
            creating = user is None
            if creating:
                username = code
                suffix = 1
                while User.objects.filter(username=username).exists():
                    suffix += 1
                    username = f"{code}-{suffix}"
                user = User(username=username, code=code)
                user.set_unusable_password()

            if "company_name" in values:
                user.company_name = _text(values.get("company_name"))[:200]
            if "inn" in values:
                inn = re.sub(r"\D", "", _text(values.get("inn")))
                if inn:
                    user.inn = inn[:12]
                    user.type = (
                        User.Type.LEGAL if len(inn) == 10 else User.Type.INDIVIDUAL
                    )
            if "kpp" in values:
                user.kpp = re.sub(r"\D", "", _text(values.get("kpp")))[:9]
            if "address" in values:
                user.address = _text(values.get("address"))[:255]
            if "debt" in values:
                d = _decimal(values.get("debt"))
                user.debt = d if d is not None else Decimal("0")

            user.save()
            if creating:
                result.created += 1
            else:
                result.updated += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append((rownum, str(exc)))
    return result
