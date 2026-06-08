import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_order_notification(order):
    """Email a placed order to its warehouse (internal).

    Returns True if an email was sent, False if the warehouse has no address.
    """
    warehouse = order.warehouse
    if not warehouse.email:
        logger.warning(
            "Order #%s: warehouse %s has no email set; notification skipped.",
            order.pk,
            warehouse.code,
        )
        return False

    subject = f"New order #{order.pk} — {warehouse.name}"
    body = render_to_string("orders/email/order_email.txt", {"order": order})
    reply_to = [order.user.email] if order.user.email else None
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[warehouse.email],
        reply_to=reply_to,
    ).send()
    return True


def send_order_confirmation(order):
    """Email a copy of the order to the buyer (confirmation).

    Returns True if an email was sent, False if the buyer has no address.
    """
    buyer_email = order.user.email
    if not buyer_email:
        logger.warning(
            "Order #%s: buyer %s has no email; confirmation skipped.",
            order.pk,
            order.user_id,
        )
        return False

    subject = f"Ваш заказ №{order.pk} принят"
    body = render_to_string("orders/email/order_confirmation.txt", {"order": order})
    reply_to = [order.warehouse.email] if order.warehouse.email else None
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[buyer_email],
        reply_to=reply_to,
    ).send()
    return True


def send_order_emails(order):
    """Send the warehouse notification and the buyer confirmation.

    Each is sent independently; a failure in one is logged and never blocks the
    other (or the order itself).
    """
    try:
        send_order_notification(order)
    except Exception:  # noqa: BLE001
        logger.exception("Order #%s: warehouse notification failed", order.pk)
    try:
        send_order_confirmation(order)
    except Exception:  # noqa: BLE001
        logger.exception("Order #%s: buyer confirmation failed", order.pk)
