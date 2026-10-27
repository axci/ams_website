"""ams CommerceML handler.

For now it implements order export only (site → 1С): 1С pulls new orders from
the site, then confirms them so they aren't sent again. Catalog/offers import
(1С → site) is intentionally left on the base no-op methods.
"""
import logging

from django.utils import timezone

from accounts.models import Company
from cml_exchange.handlers import BaseHandler
from cml_exchange.orders import Customer, OrderData
from cml_exchange.orders import OrderItem as CmlOrderItem

from .models import Order

logger = logging.getLogger("cml_exchange")

# Map a site warehouse name to its 1С склад name, when they differ. A name not
# listed is sent as-is (Новокузнецк matches 1С already).
WAREHOUSE_1C_NAMES = {
    "Кемерово": "Оптовый Кемерово",
    "Новосибирск": "Склад Новосибирск",
}

# Fixed «Ответственный» (1С пользователь) set on every exported site order.
RESPONSIBLE_1C = "Робот"


class AmsCmlHandler(BaseHandler):
    # ---------- orders: site -> 1С ----------
    def get_orders(self):
        """New orders not yet exported to 1С, oldest first."""
        orders = (
            Order.objects.filter(exported_to_1c_at__isnull=True)
            .select_related("user", "company", "warehouse")
            .prefetch_related("items__product")
            .order_by("created_at")
        )
        for o in orders:
            yield OrderData(
                id=f"site-{o.pk}",
                number=o.invoice_number,
                created=o.created_at,
                customer=self._customer(o),
                items=[
                    CmlOrderItem(
                        # Send the product identity three ways so 1С can match its
                        # номенклатура by GUID/Код/Артикул, however it's configured:
                        # Ид + Код = the 1С code (sku), Артикул = the article.
                        product_id=it.sku or (it.product.sku if it.product_id else ""),
                        name=it.name,
                        quantity=it.quantity,
                        price=it.price,
                        code=it.sku or (it.product.sku if it.product_id else ""),
                        article=(it.product.article if it.product_id else ""),
                    )
                    for it in o.items.all()
                ],
                comment=o.comment,
                status=o.get_status_display(),
                payment_method=o.get_payment_method_display(),
                delivery_method=o.get_delivery_method_display(),
                delivery_address=o.shipping_address,
                cancelled=(o.status == Order.Status.CANCELLED),
                extra=self._extra(o),
            )

    def _extra(self, o):
        """Document-level requisites 1С reads: the fixed «Ответственный» and the
        order's «Склад» (remapped to its 1С name)."""
        extra = {"Ответственный": RESPONSIBLE_1C}
        if o.warehouse_id:
            extra["Склад"] = WAREHOUSE_1C_NAMES.get(o.warehouse.name, o.warehouse.name)
        return extra

    def _customer(self, o):
        """Build the 1С контрагент from the order's company (B2B) or user."""
        c = o.company
        if c is not None:
            return Customer(
                id=c.code or f"company-{c.pk}",
                name=c.company_name or c.code or f"Компания {c.pk}",
                email=(o.user.email if o.user_id else ""),
                phone=c.phone,
                address=c.address,
                is_company=(c.type == Company.Type.LEGAL),
                inn=c.inn,
                kpp=c.kpp,
            )
        u = o.user
        return Customer(
            id=f"user-{u.pk}" if u else f"order-{o.pk}",
            name=(u.get_full_name() or u.get_username()) if u else "Покупатель",
            first_name=u.first_name if u else "",
            last_name=u.last_name if u else "",
            email=u.email if u else "",
        )

    def on_orders_exported(self, order_ids):
        """1С confirmed it loaded these orders — stop re-sending them."""
        pks = [
            int(i[5:]) for i in order_ids
            if i.startswith("site-") and i[5:].isdigit()
        ]
        if pks:
            updated = Order.objects.filter(
                pk__in=pks, exported_to_1c_at__isnull=True
            ).update(exported_to_1c_at=timezone.now())
            logger.info("1С подтвердила выгрузку заказов: %s", updated)

    def on_order_update(self, update):
        """1С sent back a change for an order (reverse direction)."""
        order = self._find_order(update)
        if order is None:
            logger.info(
                "1С: изменения по неизвестному заказу %s / %s",
                update.id, update.number,
            )
            return
        if (
            update.requisites.get("Отменен", "").strip().lower() == "true"
            and order.status != Order.Status.CANCELLED
        ):
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status"])
            logger.info("1С отменила заказ %s", order.pk)

    @staticmethod
    def _find_order(update):
        if update.id.startswith("site-") and update.id[5:].isdigit():
            found = Order.objects.filter(pk=int(update.id[5:])).first()
            if found:
                return found
        num = (update.number or "").lstrip("Ww")
        if num.isdigit():
            return Order.objects.filter(pk=int(num)).first()
        return None
