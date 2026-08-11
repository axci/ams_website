import logging
import os

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)

# Where registration requests from the public «Регистрация» page are sent.
# Overridable via env without a code change.
REGISTRATION_REQUEST_EMAIL = os.environ.get(
    "REGISTRATION_REQUEST_EMAIL", "datascientist.brescia@gmail.com"
)


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
