from django.db import models


class AboutBlock(models.Model):
    """One content block (picture + text) on the «О компании» page."""

    title = models.CharField("заголовок", max_length=200, blank=True, default="")
    picture = models.ImageField("изображение", upload_to="about/", blank=True, null=True)
    text = models.TextField("текст", blank=True)
    file = models.FileField(
        "файл",
        upload_to="about/files/",
        blank=True,
        null=True,
        help_text="Прикреплённый файл для скачивания (PDF, документ и т.д.).",
    )
    order = models.PositiveIntegerField(
        "порядок", default=0, help_text="Меньше — выше на странице."
    )
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "блок «О компании»"
        verbose_name_plural = "О компании (блоки)"

    def __str__(self):
        if self.title:
            return self.title
        if self.text:
            return (self.text[:50] + "…") if len(self.text) > 50 else self.text
        return f"Блок #{self.pk}"

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""


class CompanyDetails(models.Model):
    """Company requisites (реквизиты) — a single, admin-editable record."""

    name = models.CharField(
        "наименование",
        max_length=255,
        default="Общество с ограниченной ответственностью «Автомеханика-Сибирь»",
    )
    inn = models.CharField("ИНН", max_length=12, blank=True, default="4205361870")
    kpp = models.CharField("КПП", max_length=9, blank=True, default="420501001")
    bank = models.CharField(
        "банк",
        max_length=255,
        blank=True,
        default='ФИЛИАЛ ПАО "БАНК УРАЛСИБ" В Г. НОВОСИБИРСК',
    )
    bank_bic = models.CharField(
        "БИК банка", max_length=9, blank=True, default="045004725"
    )
    corr_account = models.CharField(
        "корр. счёт", max_length=20, blank=True, default="30101810400000000725"
    )
    settlement_account = models.CharField(
        "расчётный счёт", max_length=20, blank=True, default="40702810232210003010"
    )
    address = models.CharField(
        "адрес",
        max_length=255,
        blank=True,
        default="650903, Россия, Кемеровская область, г. Кемерово, ул. Тухачевского 52В",
    )
    director = models.CharField(
        "директор", max_length=255, blank=True, default="Моисеенко Константин Владимирович"
    )

    class Meta:
        verbose_name = "реквизиты компании"
        verbose_name_plural = "реквизиты компании"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
