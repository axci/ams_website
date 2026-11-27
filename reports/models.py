from django.db import models

from .cashflow_report import REPORT_LINES


class CashflowDocument(models.Model):
    """A cash-flow document pulled from 1С (УНФ) by the ``sync_cashflow`` command.

    1С lives on the office LAN and is unreachable from the VPS, so the office-side
    sync populates these rows (writing to the site DB, like the ERP sync) and the
    admin report reads them. The feed returns the full set each time and **reuses
    ``number`` across years/journals** (so it is not unique and there is no stable
    id), so the sync fully replaces the table rather than upserting by key.
    """

    number = models.CharField("номер", max_length=64, db_index=True)
    date = models.DateField("дата", db_index=True)
    amount = models.DecimalField("сумма", max_digits=15, decimal_places=2, default=0)
    direction = models.CharField(
        "движение", max_length=32, blank=True, default="", db_index=True,
        help_text="«Поступление» или «Расход» (как в 1С).",
    )
    source = models.CharField(
        "источник", max_length=32, blank=True, default="",
        help_text="«Касса» или «Счет».",
    )
    doc_type = models.CharField("вид документа", max_length=128, blank=True, default="")
    operation_type = models.CharField(
        "вид операции", max_length=128, blank=True, default="",
        help_text="«Вид операции» из 1С (напр. «Перевод на другой счет организации»).",
    )
    organization = models.CharField("организация", max_length=255, blank=True, default="")
    counterparty = models.CharField("контрагент", max_length=255, blank=True, default="")
    article = models.CharField("статья", max_length=255, blank=True, default="", db_index=True)
    comment = models.TextField("комментарий", blank=True, default="")
    purpose = models.TextField("назначение", blank=True, default="")
    # Manual field — NOT from 1С. The sync preserves it across the full refresh
    # (re-applied by the natural key number+doc_type+date+amount), so edits here
    # survive, unlike the 1С-sourced fields which are overwritten each sync.
    note = models.TextField(
        "заметка", blank=True, default="",
        help_text="Ваша заметка к документу. Если заметка заполнена, документ "
        "НЕ изменяется при синхронизации с 1С — строка сохраняется целиком "
        "(иначе поля из 1С перезаписываются при каждой синхронизации).",
    )
    # Set automatically for documents added by hand in the admin (not from 1С).
    # The sync deletes and recreates only the 1С rows (manual=False), so these
    # hand-entered documents survive the full refresh.
    manual = models.BooleanField(
        "добавлено вручную", default=False, editable=False,
        help_text="Документ добавлен вручную в админке (не из 1С) и не "
        "удаляется при синхронизации.",
    )
    synced_at = models.DateTimeField("обновлено синхронизацией", auto_now=True)

    class Meta:
        verbose_name = "движение денежных средств"
        verbose_name_plural = "Денежный поток (отчёт)"
        ordering = ["-date", "-number"]
        indexes = [models.Index(fields=["direction", "date"])]

    def __str__(self):
        return f"{self.number} от {self.date}: {self.amount}"

    @property
    def is_income(self):
        """True for «Поступление» (money in); everything else is treated as out."""
        return self.direction.strip().lower().startswith("поступ")


class CashflowArticleMapping(models.Model):
    """Admin-editable override: map a 1С «Статья» to a line of the ОДДС, or
    exclude it. Built-in defaults live in ``cashflow_report.ARTICLE_TO_LINE``;
    rows here override them, and articles missing from both are flagged after a
    report is built."""

    article = models.CharField(
        "статья (из 1С)", max_length=255, unique=True,
        help_text="Название статьи ДДС, как в 1С (регистр не важен).",
    )
    report_line = models.CharField(
        "строка отчёта", max_length=255, blank=True, default="",
        choices=[(line, line) for line in REPORT_LINES],
        help_text="Куда отнести статью в отчёте ОДДС.",
    )
    exclude = models.BooleanField(
        "исключить из отчёта", default=False,
        help_text="Не учитывать статью (например, перемещения между своими кассами/счетами).",
    )

    class Meta:
        verbose_name = "сопоставление статьи ДДС"
        verbose_name_plural = "Денежный поток: сопоставление статей"
        ordering = ["article"]

    def __str__(self):
        target = "(исключить)" if self.exclude else (self.report_line or "—")
        return f"{self.article} → {target}"


class Receipt(models.Model):
    """A goods receipt pulled from 1С (УНФ) by the ``sync_receipts`` command — the
    cost side of the profit report (what we paid suppliers, plus freight/landed
    costs). Mirrors the [[cashflow-report]] data flow: the office-side sync fetches
    the full feed and replaces the table; the lines hang off :class:`ReceiptLine`.

    ``operationType`` is one of «Поступление от поставщика» (a purchase), «Возврат
    от комиссионера» or «Возврат от покупателя» (goods coming back) — all kept.
    ``(number, date)`` is unique in the feed but not enforced here (the sync does a
    full refresh and must tolerate any future duplicate without aborting).
    """

    number = models.CharField("номер", max_length=32, db_index=True)
    date = models.DateField("дата", db_index=True)
    organization = models.CharField("организация", max_length=128, blank=True, default="")
    counterparty = models.CharField("контрагент", max_length=255, blank=True, default="")
    operation_type = models.CharField(
        "вид операции", max_length=64, blank=True, default="", db_index=True,
        help_text="«Поступление от поставщика», «Возврат от комиссионера» или "
        "«Возврат от покупателя».",
    )
    warehouse = models.CharField("склад", max_length=128, blank=True, default="")
    amount = models.DecimalField("сумма документа", max_digits=15, decimal_places=2, default=0)
    synced_at = models.DateTimeField("обновлено синхронизацией", auto_now=True)

    class Meta:
        verbose_name = "поступление товаров"
        verbose_name_plural = "Поступления товаров (закупки/возвраты)"
        ordering = ["-date", "-number"]
        indexes = [models.Index(fields=["operation_type", "date"])]

    def __str__(self):
        return f"{self.number} от {self.date}: {self.amount}"


class ReceiptLine(models.Model):
    """One line of a :class:`Receipt`: a stock item (``is_expense=False``) or an
    additional-cost line (``is_expense=True``, e.g. «Транспортные услуги» freight).
    Both arrive from 1С with the same shape (product/quantity/price/sum); ``sum`` is
    stored as-is because ~4% of feed lines have ``sum != quantity*price``."""

    receipt = models.ForeignKey(
        Receipt, on_delete=models.CASCADE, related_name="lines", verbose_name="поступление",
    )
    is_expense = models.BooleanField(
        "доп. расход", default=False,
        help_text="Строка дополнительных расходов (напр. доставка), а не товар.",
    )
    product = models.CharField("номенклатура", max_length=255, blank=True, default="")
    quantity = models.DecimalField("количество", max_digits=15, decimal_places=3, default=0)
    price = models.DecimalField("цена", max_digits=15, decimal_places=2, default=0)
    line_sum = models.DecimalField("сумма", max_digits=15, decimal_places=2, default=0)

    class Meta:
        verbose_name = "строка поступления"
        verbose_name_plural = "строки поступления"
        ordering = ["id"]

    def __str__(self):
        kind = "расход" if self.is_expense else "товар"
        return f"{self.product} ({kind}): {self.quantity} × {self.price} = {self.line_sum}"
