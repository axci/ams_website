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
    short_name = models.CharField(
        "краткое наименование",
        max_length=255,
        blank=True,
        default="ООО «Автомеханика-Сибирь»",
    )
    legal_form = models.CharField(
        "организационно-правовая форма",
        max_length=255,
        blank=True,
        default="Общество с ограниченной ответственностью",
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
    card_pdf = models.FileField(
        "карточка предприятия (PDF)",
        upload_to="about/files/",
        blank=True,
        null=True,
        help_text="PDF с реквизитами для скачивания на странице «О компании».",
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


class AboutPage(models.Model):
    """Singleton holding the editable text of the «О компании» page. Repeatable
    items (spec tiles, client tags, brands, centres, regions) are separate models
    below. Requisites come from CompanyDetails."""

    # --- Hero ---
    hero_eyebrow = models.CharField("надзаголовок", max_length=100, blank=True, default="О компании")
    hero_title = models.CharField(
        "заголовок",
        max_length=200,
        default="Смазочные материалы для всей",
    )
    hero_title_accent = models.CharField(
        "выделенное слово",
        max_length=100,
        blank=True,
        default="Сибири",
        help_text="Последнее слово заголовка, выделенное акцентным цветом.",
    )
    hero_lead = models.TextField(
        "вводный текст",
        blank=True,
        default=(
            "«Автомеханика-Сибирь» — один из ведущих поставщиков моторных, "
            "трансмиссионных и индустриальных масел, технических жидкостей и "
            "автохимии. Работаем с розничными, оптовыми и корпоративными "
            "клиентами с 2005 года."
        ),
    )
    # --- Профиль ---
    profile_eyebrow = models.CharField(max_length=100, blank=True, default="Профиль")
    profile_title = models.CharField(max_length=200, blank=True, default="Кто мы")
    profile_side_label = models.CharField(max_length=100, blank=True, default="Направление поставок")
    profile_lead = models.TextField(
        blank=True,
        default=(
            "Наше основное направление — поставка моторных, трансмиссионных и "
            "индустриальных масел, технических жидкостей, автохимии и "
            "сопутствующих товаров для легкового, коммерческого и промышленного "
            "транспорта."
        ),
    )
    profile_body = models.TextField(
        blank=True,
        default=(
            "Собственная торговая команда позволяет оперативно взаимодействовать "
            "с клиентами, выстраивать долгосрочные партнёрские отношения и "
            "обеспечивать высокий уровень сервиса на каждом этапе сотрудничества "
            "— от подбора продукции до организации регулярных поставок."
        ),
    )
    profile_pull = models.CharField(
        max_length=255, blank=True,
        default="Более 20 лет на рынке смазочных материалов Сибири.",
    )
    # --- Клиенты ---
    clients_eyebrow = models.CharField(max_length=100, blank=True, default="Клиенты и опыт")
    clients_title = models.CharField(max_length=200, blank=True, default="Работаем с федеральными сетями")
    clients_body = models.TextField(
        blank=True,
        default=(
            "Обладаем значительным опытом обслуживания крупных сетевых клиентов. "
            "Понимая специфику работы с федеральными и региональными сетями, "
            "строго соблюдаем требования к ассортименту, срокам поставки и "
            "стабильности товарного запаса. Участвуем в тендерах на поставку "
            "смазочных материалов для государственных и коммерческих предприятий."
        ),
    )
    # --- Бренды ---
    brands_eyebrow = models.CharField(max_length=100, blank=True, default="Наши бренды")
    brands_title = models.CharField(max_length=200, blank=True, default="Что мы поставляем")
    # --- География ---
    geo_eyebrow = models.CharField(max_length=100, blank=True, default="География поставок")
    geo_title = models.CharField(max_length=200, blank=True, default="Три центра, пять регионов")
    # --- Реквизиты ---
    req_eyebrow = models.CharField(max_length=100, blank=True, default="Реквизиты")
    req_title = models.CharField(max_length=200, blank=True, default="Данные компании")
    req_note = models.TextField(
        blank=True,
        default="Полные реквизиты в формате PDF для оформления договоров и заявок.",
    )

    class Meta:
        verbose_name = "страница «О компании»"
        verbose_name_plural = "страница «О компании»"

    def __str__(self):
        return "Страница «О компании»"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AboutSpec(models.Model):
    """A hero spec tile (e.g. «Год основания / 2005»)."""

    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, default=1, related_name="specs")
    label = models.CharField("метка", max_length=60)
    value = models.CharField("значение", max_length=60)
    subtitle = models.CharField("подпись", max_length=120, blank=True)
    order = models.PositiveIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "показатель (Hero)"
        verbose_name_plural = "показатели (Hero)"

    def __str__(self):
        return f"{self.label}: {self.value}"


class ClientTag(models.Model):
    """A client / experience tag chip."""

    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, default=1, related_name="client_tags")
    text = models.CharField("текст", max_length=80)
    accent = models.BooleanField("акцент", default=False, help_text="Выделить акцентным цветом.")
    order = models.PositiveIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "тег клиента"
        verbose_name_plural = "теги клиентов"

    def __str__(self):
        return self.text


class AboutBrandBlock(models.Model):
    """A brand block (role + heading + description + chips) in the «Бренды» section."""

    role = models.CharField("роль", max_length=80, blank=True, help_text="Напр.: «Официальный дистрибьютор».")
    heading = models.CharField("заголовок", max_length=160)
    description = models.TextField("описание", blank=True)
    order = models.PositiveIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "блок бренда"
        verbose_name_plural = "блоки брендов"

    def __str__(self):
        return self.heading


class AboutBrandChip(models.Model):
    """A single brand chip (name + subtitle) inside a brand block."""

    block = models.ForeignKey(AboutBrandBlock, on_delete=models.CASCADE, related_name="chips")
    name = models.CharField("название", max_length=80)
    subtitle = models.CharField("подпись", max_length=120, blank=True)
    url = models.CharField(
        "ссылка", max_length=300, blank=True,
        help_text="Куда ведёт плитка бренда. Напр.: /?brand=mannol",
    )
    image = models.ImageField(
        "логотип", upload_to="about/brands/", blank=True, null=True,
        help_text="Логотип бренда (необязательно).",
    )
    order = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "бренд (плитка)"
        verbose_name_plural = "бренды (плитки)"

    def __str__(self):
        return self.name


class SupplyCenter(models.Model):
    """A supply centre (город) shown in «География»."""

    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, default=1, related_name="centers")
    name = models.CharField("город", max_length=80)
    order = models.PositiveIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "центр поставок"
        verbose_name_plural = "центры поставок"

    def __str__(self):
        return self.name


class SupplyRegion(models.Model):
    """A supply region shown in «География»."""

    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, default=1, related_name="regions")
    name = models.CharField("регион", max_length=120)
    order = models.PositiveIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликовано", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "регион поставок"
        verbose_name_plural = "регионы поставок"

    def __str__(self):
        return self.name
