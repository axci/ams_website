"""Import client order spreadsheets that arrive by email.

Connects to the configured IMAP mailbox, finds messages from whitelisted
senders that carry an .xlsx attachment, and turns each «Точка продаж» section
into a pending Order (see :mod:`orders.email_import`). Messages are matched to
:class:`orders.models.ImportedOrderEmail` by Message-ID so a run never imports
the same email twice; processed messages are flagged \\Seen.

Usage::

    python manage.py import_email_orders            # process new (UNSEEN) mail
    python manage.py import_email_orders --dry-run   # report only, write nothing
    python manage.py import_email_orders --all       # also re-scan read mail

Configuration lives in settings.EMAIL_ORDER_IMPORT (fed from the environment):
ORDER_IMAP_HOST / ORDER_IMAP_USER / ORDER_IMAP_PASSWORD / ORDER_ALLOWED_SENDERS
/ ORDER_DEFAULT_WAREHOUSE / ORDER_SENDER_USER_MAP.
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
    parse_order_workbook,
    resolve_user,
    resolve_warehouse,
)
from orders.models import ImportedOrderEmail

logger = logging.getLogger("orders.email_import")

SPREADSHEET_CT = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _decode(value):
    """Decode an RFC 2047 header (Subject / filename) to a plain string."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _xlsx_attachments(msg):
    """Yield (filename, bytes) for each .xlsx attachment of a message."""
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = _decode(part.get_filename())
        content_type = (part.get_content_type() or "").lower()
        is_xlsx = filename.lower().endswith(".xlsx") or content_type == SPREADSHEET_CT
        if not is_xlsx:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            yield (filename or "order.xlsx", payload)


class Command(BaseCommand):
    help = "Импорт заказов из xlsx-вложений писем (IMAP)."

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
            help="Максимум писем за один запуск (по умолчанию 25).",
        )
        parser.add_argument(
            "--mailbox", default=None,
            help="Переопределить ящик/папку (по умолчанию из настроек).",
        )

    def handle(self, *args, **opts):
        config = get_config()
        dry_run = opts["dry_run"]

        username = config.get("USERNAME", "")
        password = config.get("PASSWORD", "")
        if not username or not password:
            raise CommandError(
                "Не заданы ORDER_IMAP_USER / ORDER_IMAP_PASSWORD."
            )

        warehouse = resolve_warehouse(config)
        if warehouse is None:
            raise CommandError(
                "Склад по умолчанию не найден: "
                f"{config.get('DEFAULT_WAREHOUSE')!r}. Проверьте ORDER_DEFAULT_WAREHOUSE."
            )

        allowed = {a.lower() for a in config.get("ALLOWED_SENDERS", [])}
        if not allowed:
            raise CommandError(
                "ORDER_ALLOWED_SENDERS пуст — укажите хотя бы одного отправителя, "
                "иначе письма от кого угодно попали бы в заказы."
            )
        host = config.get("IMAP_HOST", "imap.yandex.ru")
        port = int(config.get("IMAP_PORT", 993))
        mailbox = opts["mailbox"] or config.get("MAILBOX", "INBOX")

        self.stdout.write(
            f"Подключение к {host}:{port} как {username}, ящик {mailbox}"
            + (" [DRY-RUN]" if dry_run else "")
        )

        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(username, password)
            conn.select(mailbox)
            criteria = "ALL" if opts["all"] else "UNSEEN"
            typ, data = conn.search(None, criteria)
            if typ != "OK":
                raise CommandError(f"IMAP SEARCH вернул {typ}.")
            uids = data[0].split()
            if opts["limit"]:
                uids = uids[-opts["limit"]:]
            self.stdout.write(f"Найдено писем ({criteria}): {len(uids)}")

            totals = {"emails": 0, "orders": 0, "skipped_sender": 0, "no_user": 0}
            for uid in uids:
                self._process_uid(
                    conn, uid, allowed, warehouse, config, dry_run, host, totals
                )

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

    # -- per-message -------------------------------------------------------- #
    def _process_uid(self, conn, uid, allowed, warehouse, config, dry_run, host, totals):
        typ, msg_data = conn.fetch(uid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            self.stderr.write(f"UID {uid!r}: не удалось получить письмо.")
            return
        raw = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw)

        sender = parseaddr(msg.get("From", ""))[1].lower()
        subject = _decode(msg.get("Subject", ""))
        if sender not in allowed:
            totals["skipped_sender"] += 1
            return  # leave unseen; not our client

        message_id = (msg.get("Message-ID") or "").strip()
        if not message_id:
            message_id = f"<ams-{hashlib.sha1(raw).hexdigest()}@{host}>"

        if ImportedOrderEmail.objects.filter(message_id=message_id).exists():
            self._mark_seen(conn, uid, dry_run)
            return  # already imported

        attachments = list(_xlsx_attachments(msg))
        if not attachments:
            self.stdout.write(f"  {sender}: «{subject}» — нет xlsx-вложений, пропуск.")
            return

        user = resolve_user(sender, config)
        if user is None:
            totals["no_user"] += 1
            self.stderr.write(
                f"  {sender}: «{subject}» — отправитель не сопоставлен с аккаунтом "
                "(добавьте его в ORDER_SENDER_USER_MAP). Оставлено непрочитанным."
            )
            return  # leave unseen so it imports once the mapping is fixed

        # Parse every attachment into sections.
        sections = []
        for filename, payload in attachments:
            try:
                sections.extend(parse_order_workbook(io.BytesIO(payload)))
            except Exception as exc:
                self.stderr.write(f"  Не удалось разобрать {filename}: {exc}")
        if not sections:
            self.stdout.write(f"  {sender}: «{subject}» — в файлах нет позиций, пропуск.")
            return

        received_at = None
        try:
            received_at = parsedate_to_datetime(msg.get("Date"))
        except Exception:
            pass

        label = f"{sender}, {subject}" if subject else sender

        if dry_run:
            result = create_orders_for_email(
                sections, user=user, warehouse=warehouse,
                source_email=None, source_label=label, dry_run=True,
            )
            totals["emails"] += 1
            totals["orders"] += len(result.created_orders)
            self.stdout.write(
                f"  [DRY] {sender}: «{subject}» → {result.summary()}"
            )
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
                sections, user=user, warehouse=warehouse,
                source_email=source_email, source_label=label,
            )
            source_email.order_count = len(result.created_orders)
            source_email.report = result.render_report()
            source_email.save(update_fields=["order_count", "report"])

        totals["emails"] += 1
        totals["orders"] += len(result.created_orders)
        logger.info("Импорт из письма %s: %s", message_id, result.summary())
        self.stdout.write(self.style.SUCCESS(
            f"  {sender}: «{subject}» → {result.summary()}"
        ))
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
