import logging
import os

from django.conf import settings
from django.core.mail import EmailMessage
from django.urls import reverse

logger = logging.getLogger(__name__)

# Where registration requests from the public «Регистрация» page are sent.
# Overridable via env without a code change.
REGISTRATION_REQUEST_EMAIL = os.environ.get(
    "REGISTRATION_REQUEST_EMAIL", "datascientist.brescia@gmail.com"
)

# Canonical public site URL used for links in outgoing mail — kept independent
# of which domain an admin happened to use. Overridable via env.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://automech.su")


def send_registration_request(company_name, inn, email):
    """Email a registration request to the sales inbox. Raises on send failure."""
    subject = f"Заявка на регистрацию: {company_name}"
    body = (
        "Новая заявка на регистрацию с сайта:\n\n"
        f"Наименование компании: {company_name}\n"
        f"ИНН: {inn}\n"
        f"Email: {email}\n"
    )
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[REGISTRATION_REQUEST_EMAIL],
        reply_to=[email],
    ).send()


def send_credentials(to_email, name, username, password):
    """Email a new client their login and password. Raises on send failure."""
    login_url = SITE_BASE_URL.rstrip("/") + reverse("login")
    greeting = f"Здравствуйте, {name}!" if name else "Здравствуйте!"
    subject = "Доступ к личному кабинету — Автомеханика-Сибирь"
    body = (
        f"{greeting}\n\n"
        "Благодарим за регистрацию на нашем сайте. "
        "Ниже — данные для входа в личный кабинет:\n\n"
        f"Логин: {username}\n"
        f"Пароль: {password}\n"
        f"Адрес входа: {login_url}\n\n"
        "В целях безопасности рекомендуем сменить пароль после первого входа: "
        "Профиль → «Сменить пароль».\n\n"
        "Если у вас возникнут вопросы, свяжитесь с вашим персональным менеджером.\n\n"
        "С уважением,\n"
        "команда «Автомеханика-Сибирь»"
    )
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    ).send()
