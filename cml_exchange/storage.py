"""Файлы обмена: приём от 1С, безопасные пути, состояние между запросами."""
import json
import shutil
from pathlib import Path, PurePosixPath

from . import conf

KINDS = ("catalog", "sale")


class ExchangeError(Exception):
    """Ошибка, текст которой показывается пользователю 1С."""


def type_dir(kind: str) -> Path:
    if kind not in KINDS:
        raise ExchangeError(f"Неизвестный тип обмена: {kind}")
    path = conf.exchange_dir() / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def reset(kind: str) -> None:
    """Очищает папку перед новым сеансом обмена (файлы прошлого сеанса удаляются)."""
    path = conf.exchange_dir() / kind
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def safe_path(kind: str, filename: str) -> Path:
    """Путь к файлу внутри папки обмена. Не даёт выйти за её пределы."""
    if not filename:
        raise ExchangeError("Не указано имя файла (параметр filename)")
    parts = PurePosixPath(filename.replace("\\", "/")).parts
    if not parts or parts[0] == "/" or ".." in parts or ":" in parts[0]:
        raise ExchangeError(f"Недопустимое имя файла: {filename}")
    base = type_dir(kind).resolve()
    target = base.joinpath(*parts).resolve()
    if base != target and base not in target.parents:
        raise ExchangeError(f"Недопустимое имя файла: {filename}")
    return target


def append_request_body(request, target: Path, chunk_size: int = 64 * 1024) -> int:
    """Дописывает тело запроса в файл. 1С может прислать большой файл частями."""
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(target, "ab") as fh:
        while True:
            chunk = request.read(chunk_size)
            if not chunk:
                break
            fh.write(chunk)
            written += len(chunk)
    return written


def _state_file(name: str) -> Path:
    path = conf.exchange_dir() / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{name}.json"


def load_state(name: str) -> dict:
    path = _state_file(name)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(name: str, data: dict) -> None:
    path = _state_file(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
