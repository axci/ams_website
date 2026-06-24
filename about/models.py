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
