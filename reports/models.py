from django.db import models


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
        help_text="Ваша заметка к документу. Сохраняется при синхронизации "
        "(в отличие от полей, которые приходят из 1С).",
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
