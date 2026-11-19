from django.db import models


class CashflowDocument(models.Model):
    """A cash-flow document pulled from 1С (УНФ) by the ``sync_cashflow`` command.

    One row per 1С document, keyed by its ``number``. 1С lives on the office LAN
    and is unreachable from the VPS, so the office-side sync populates these rows
    (writing to the site DB, like the ERP sync) and the admin report reads them.
    """

    number = models.CharField("номер", max_length=64, unique=True)
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
