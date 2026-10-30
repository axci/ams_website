"""Import client order spreadsheets that arrive by email.

Connects to the configured IMAP mailbox and walks each *source profile*
(``settings.EMAIL_ORDER_IMPORT["SOURCES"]``): for every profile it opens that
profile's folder, finds messages from allowed senders carrying an .xlsx/.xls
attachment, and turns them into pending Orders (see :mod:`orders.email_import`).
Messages are matched to :class:`orders.models.ImportedOrderEmail` by Message-ID
so a run never imports the same email twice; processed messages are flagged
\\Seen.

Usage::

    python manage.py import_email_orders              # process new (UNSEEN) mail
    python manage.py import_email_orders --dry-run     # report only, write nothing
    python manage.py import_email_orders --all         # also re-scan read mail
    python manage.py import_email_orders --source nkoil  # one profile only
"""

import email as email_lib
import hashlib
import imaplib
import io
import logging
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

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


def _decode(value):
    """Decode an RFC 2047 header (Subject / filename) to a plain string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


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
    help = "Импорт заказов из xlsx/xls-вложений писем (IMAP)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Разобрать и показать результат, ничего не записывая.",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Сканировать все письма, а не только непрочитанные.",
        )
        parser.add_argument(
            "--limit", type=int, default=25,
            help="Максимум писем на источник за запуск (по умолчанию 25).",
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

        host = config.get("IMAP_HOST", "imap.yandex.ru")
        port = int(config.get("IMAP_PORT", 993))
        self.stdout.write(
            f"Подключение к {host}:{port} как {username}"
            + (" [DRY-RUN]" if dry_run else "")
        )

        totals = {"emails": 0, "orders": 0, "skipped_sender": 0, "no_user": 0}
        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(username, password)
            for source in sources:
                self._process_source(conn, source, warehouse, dry_run, host, opts, totals)
            self.stdout.write(self.style.SUCCESS(
                "Готово: обработано писем {emails}, создано заказов {orders}, "
                "пропущено по отправителю {skipped_sender}, без аккаунта {no_user}."
                .format(**totals)
            ))
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    # -- per-source --------------------------------------------------------- #
    def _process_source(self, conn, source, warehouse, dry_run, host, opts, totals):
        name = source.get("name", "?")
        folder = source.get("folder", "INBOX")
        typ, _ = conn.select(folder)
        if typ != "OK":
            self.stderr.write(f"[{name}] не удалось открыть папку {folder!r}: {typ}.")
            return
        criteria = "ALL" if opts["all"] else "UNSEEN"
        typ, data = conn.search(None, criteria)
        if typ != "OK":
            self.stderr.write(f"[{name}] IMAP SEARCH вернул {typ}.")
            return
        uids = data[0].split()
        if opts["limit"]:
            uids = uids[-opts["limit"]:]
        self.stdout.write(f"[{name}] папка {folder}: писем ({criteria}) {len(uids)}")
        for uid in uids:
            self._process_uid(conn, uid, source, warehouse, dry_run, host, totals)

    # -- per-message -------------------------------------------------------- #
    def _process_uid(self, conn, uid, source, warehouse, dry_run, host, totals):
        name = source.get("name", "?")
        typ, msg_data = conn.fetch(uid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            self.stderr.write(f"[{name}] UID {uid!r}: не удалось получить письмо.")
            return
        raw = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw)

        sender = parseaddr(msg.get("From", ""))[1].lower()
        subject = _decode(msg.get("Subject", ""))
        if not sender_allowed(sender, source):
            totals["skipped_sender"] += 1
            return  # leave unseen; not a client of this source

        message_id = (msg.get("Message-ID") or "").strip()
        if not message_id:
            message_id = f"<ams-{hashlib.sha1(raw).hexdigest()}@{host}>"
        if ImportedOrderEmail.objects.filter(message_id=message_id).exists():
            self._mark_seen(conn, uid, dry_run)
            return  # already imported

        attachments = list(_spreadsheet_attachments(msg))
        if not attachments:
            self.stdout.write(f"  [{name}] {sender}: «{subject}» — нет вложений, пропуск.")
            return

        user = resolve_user(sender, source)
        if user is None:
            totals["no_user"] += 1
            self.stderr.write(
                f"  [{name}] {sender}: «{subject}» — отправитель не сопоставлен "
                "с аккаунтом. Оставлено непрочитанным."
            )
            return  # leave unseen so it imports once the mapping is fixed

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

        totals["emails"] += 1
        totals["orders"] += len(result.created_orders)
        logger.info("[%s] импорт из письма %s: %s", name, message_id, result.summary())
        self.stdout.write(self.style.SUCCESS(f"  [{name}] {sender}: «{subject}» → {result.summary()}"))
        if result.unmatched:
            self.stdout.write(self.style.WARNING(
                f"       не найдено товаров: {len(result.unmatched)} "
                "(см. отчёт в админке → «Импорт заказов из почты»)."
            ))
        self._mark_seen(conn, uid, dry_run)

    def _mark_seen(self, conn, uid, dry_run):
        if dry_run:
            return
        try:
            conn.store(uid, "+FLAGS", "\\Seen")
        except Exception as exc:
            self.stderr.write(f"  Не удалось пометить письмо прочитанным: {exc}")
