from django.db import models
from django.urls import reverse
from django.utils import timezone


def default_news_date():
    """Today's date (timezone-safe); default for a new post."""
    return timezone.now().date()


class News(models.Model):
    """A news / announcement post for the public «Новости» section."""

    title = models.CharField("заголовок", max_length=200)
    picture = models.ImageField("изображение", upload_to="news/", blank=True, null=True)
    text = models.TextField("текст")
    date = models.DateField("дата", default=default_news_date)
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name = "новость"
        verbose_name_plural = "новости"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("news:detail", args=[self.pk])
