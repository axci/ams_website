"""Import client order spreadsheets that arrive by email.

Connects to the configured IMAP mailbox and walks each *source profile*
(``settings.EMAIL_ORDER_IMPORT["SOURCES"]``): for every profile it opens that
profile's folder, finds order emails and turns them into pending Orders (see
:mod:`orders.email_import`).

Which emails are imported is decided by two things, never by read/unread (so a
manager opening a message in webmail changes nothing):

* a **date cutoff** (``ORDER_SINCE`` / ``--since``) — only emails dated strictly
  after it are considered, which excludes pre-automation orders handled manually;
* **Message-ID dedup** (:class:`orders.models.ImportedOrderEmail`) — the same
  email is never imported twice.

Usage::

    python manage.py import_email_orders              # emails after ORDER_SINCE
    python manage.py import_email_orders --dry-run     # report only, write nothing
    python manage.py import_email_orders --since 2026-10-30
    python manage.py import_email_orders --all         # ignore the cutoff (full load)
    python manage.py import_email_orders --source nkoil  # one profile only
"""

import email as email_lib
import hashlib
import imaplib
import io
import logging
from datetime import date, timezone as dt_timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone as dj_timezone

from orders.email_import import (
    create_orders_for_email,
    get_config,
    get_sources,
    parse_attachment,
    resolve_user,
    resolve_warehouse,
    sender_allowed,
)
from orders.models import ImportedOrderEmail

logger = logging.getLogger("orders.email_import")

SPREADSHEET_CTS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-excel",  # .xls
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(d):
    """A date as IMAP SEARCH wants it, e.g. 30-Oct-2026 (locale-independent)."""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _decode(value):
    """Decode an RFC 2047 header (Subject / filename) to a plain string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _local_date(date_header):
    """The local (site-timezone) calendar date of an email's Date header, or
    None if it's missing/unparseable."""
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dj_timezone.localtime(dt).date()


def _spreadsheet_attachments(msg):
    """Yield (filename, bytes) for each .xlsx/.xls attachment of a message."""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = _decode(part.get_filename())
        content_type = (part.get_content_type() or "").lower()
        lower = filename.lower()
        is_sheet = lower.endswith((".xlsx", ".xls")) or content_type in SPREADSHEET_CTS
        if not is_sheet:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            yield (filename or "order.xlsx", payload)


class Command(BaseCommand):
    help = "Импорт заказов из xlsx/xls-вложений писем (IMAP), по дате отсечки."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Разобрать и показать результат, ничего не записывая.",
        )
        parser.add_argument(
            "--since", default=None,
            help="Импортировать письма строго позже этой даты (ГГГГ-ММ-ДД); "
                 "по умолчанию из ORDER_SINCE.",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Игнорировать дату отсечки — разовая полная загрузка.",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Максимум писем на источник (0 — без ограничения).",
        )
        parser.add_argument(
            "--source", default=None,
            help="Обработать только источник с этим именем (по умолчанию — все).",
        )

    def handle(self, *args, **opts):
        config = get_config()
        dry_run = opts["dry_run"]

        username = config.get("USERNAME", "")
        password = config.get("PASSWORD", "")
        if not username or not password:
            raise CommandError("Не заданы ORDER_IMAP_USER / ORDER_IMAP_PASSWORD.")

        warehouse = resolve_warehouse(config)
        if warehouse is None:
            raise CommandError(
                "Склад по умолчанию не найден: "
                f"{config.get('DEFAULT_WAREHOUSE')!r}. Проверьте ORDER_DEFAULT_WAREHOUSE."
            )

        sources = get_sources(config)
        if opts["source"]:
            sources = [s for s in sources if s.get("name") == opts["source"]]
            if not sources:
                raise CommandError(f"Источник не найден: {opts['source']!r}.")
        if not sources:
            raise CommandError("Не настроен ни один источник (ORDER_SOURCES).")

        cutoff = None
        if not opts["all"]:
            raw = (opts["since"] or config.get("SINCE", "") or "").strip()
            if raw:
                try:
                    cutoff = date.fromisoformat(raw)
                except ValueError:
                    raise CommandError(
                        f"Неверная дата отсечки: {raw!r} (ожидается ГГГГ-ММ-ДД)."
                    )

        # One query up front; dedup checks are then in-memory.
        imported_ids = set(ImportedOrderEmail.objects.values_list("message_id", flat=True))

        host = config.get("IMAP_HOST", "imap.yandex.ru")
        port = int(config.get("IMAP_PORT", 993))
        self.stdout.write(
            f"Подключение к {host}:{port} как {username}; "
            + (f"письма после {cutoff}" if cutoff else "все письма (без отсечки)")
            + (" [DRY-RUN]" if dry_run else "")
        )

        totals = {"emails": 0, "orders": 0, "skipped_sender": 0,
                  "before_cutoff": 0, "no_user": 0}
        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(username, password)
            for source in sources:
                self._process_source(
                    conn, source, warehouse, cutoff, imported_ids, dry_run, host, opts, totals
                )
            self.stdout.write(self.style.SUCCESS(
                "Готово: обработано писем {emails}, создано заказов {orders}, "
                "пропущено по отправителю {skipped_sender}, раньше отсечки "
                "{before_cutoff}, без аккаунта {no_user}.".format(**totals)
            ))
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    # -- per-source --------------------------------------------------------- #
    def _process_source(self, conn, source, warehouse, cutoff, imported_ids,
                         dry_run, host, opts, totals):
        name = source.get("name", "?")
        folder = source.get("folder", "INBOX")
        typ, _ = conn.select(folder)
        if typ != "OK":
            self.stderr.write(f"[{name}] не удалось открыть папку {folder!r}: {typ}.")
            return
        # Server-side date filter (coarse, by INTERNALDATE); the Date-header check
        # per message is the precise "strictly after" gate.
        if cutoff is not None:
            typ, data = conn.search(None, "SINCE", _imap_date(cutoff))
        else:
            typ, data = conn.search(None, "ALL")
        if typ != "OK":
            self.stderr.write(f"[{name}] IMAP SEARCH вернул {typ}.")
            return
        uids = data[0].split()
        if opts["limit"] and opts["limit"] > 0:
            uids = uids[-opts["limit"]:]
        self.stdout.write(f"[{name}] папка {folder}: писем к проверке {len(uids)}")
        for uid in uids:
            self._process_uid(
                conn, uid, source, warehouse, cutoff, imported_ids, dry_run, host, totals
            )

    # -- per-message -------------------------------------------------------- #
    def _process_uid(self, conn, uid, source, warehouse, cutoff, imported_ids,
                     dry_run, host, totals):
        name = source.get("name", "?")
        # Cheap header peek first (does not touch the \Seen flag).
        typ, hdata = conn.fetch(
            uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM DATE SUBJECT)])"
        )
        if typ != "OK" or not hdata or not isinstance(hdata[0], tuple):
            self.stderr.write(f"[{name}] UID {uid!r}: не удалось получить заголовки.")
            return
        head = email_lib.message_from_bytes(hdata[0][1])
        sender = parseaddr(head.get("From", ""))[1].lower()
        subject = _decode(head.get("Subject", ""))

        if not sender_allowed(sender, source):
            totals["skipped_sender"] += 1
            return

        if cutoff is not None:
            msg_date = _local_date(head.get("Date"))
            if msg_date is None:
                self.stderr.write(
                    f"  [{name}] {sender}: «{subject}» — без даты, пропуск."
                )
                return
            if msg_date <= cutoff:
                totals["before_cutoff"] += 1
                return  # pre-cutoff (old / manually handled)

        message_id = (head.get("Message-ID") or "").strip()
        if message_id and message_id in imported_ids:
            return  # already imported

        # Passed the cheap checks — fetch the full message (still peek, no \Seen).
        typ, bdata = conn.fetch(uid, "(BODY.PEEK[])")
        if typ != "OK" or not bdata or not isinstance(bdata[0], tuple):
            self.stderr.write(f"[{name}] UID {uid!r}: не удалось получить письмо.")
            return
        raw = bdata[0][1]
        if not message_id:
            message_id = f"<ams-{hashlib.sha1(raw).hexdigest()}@{host}>"
            if message_id in imported_ids:
                return

        msg = email_lib.message_from_bytes(raw)
        attachments = list(_spreadsheet_attachments(msg))
        if not attachments:
            self.stdout.write(f"  [{name}] {sender}: «{subject}» — нет вложений, пропуск.")
            return

        user = resolve_user(sender, source)
        if user is None:
            totals["no_user"] += 1
            self.stderr.write(
                f"  [{name}] {sender}: «{subject}» — отправитель не сопоставлен с аккаунтом."
            )
            return

        fmt = source.get("format", "nkoil_sections")
        sections = []
        for filename, payload in attachments:
            try:
                sections.extend(parse_attachment(filename, payload, fmt))
            except Exception as exc:
                self.stderr.write(f"  [{name}] не удалось разобрать {filename}: {exc}")
        if not sections:
            self.stdout.write(f"  [{name}] {sender}: «{subject}» — нет позиций, пропуск.")
            return

        received_at = None
        try:
            received_at = parsedate_to_datetime(msg.get("Date"))
        except Exception:
            pass

        match_by = source.get("match_by", "nkoil_code")
        label = f"{sender}, {subject}" if subject else sender

        if dry_run:
            result = create_orders_for_email(
                sections, user=user, warehouse=warehouse, match_by=match_by,
                source_email=None, source_label=label, dry_run=True,
            )
            totals["emails"] += 1
            totals["orders"] += len(result.created_orders)
            self.stdout.write(f"  [DRY][{name}] {sender}: «{subject}» → {result.summary()}")
            for text in result.render_report().splitlines()[1:]:
                self.stdout.write(f"       {text}")
            return

        with transaction.atomic():
            source_email = ImportedOrderEmail.objects.create(
                message_id=message_id,
                sender=sender,
                subject=subject[:500],
                received_at=received_at,
            )
            result = create_orders_for_email(
                sections, user=user, warehouse=warehouse, match_by=match_by,
                source_email=source_email, source_label=label,
            )
            source_email.order_count = len(result.created_orders)
            source_email.report = result.render_report()
            source_email.save(update_fields=["order_count", "report"])
        imported_ids.add(message_id)

        totals["emails"] += 1
        totals["orders"] += len(result.created_orders)
        logger.info("[%s] импорт из письма %s: %s", name, message_id, result.summary())
        self.stdout.write(self.style.SUCCESS(f"  [{name}] {sender}: «{subject}» → {result.summary()}"))
        if result.unmatched:
            self.stdout.write(self.style.WARNING(
                f"       не найдено товаров: {len(result.unmatched)} "
                "(см. отчёт в админке → «Импорт заказов из почты»)."
            ))
