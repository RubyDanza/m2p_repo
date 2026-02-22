from django.db import models
from django.conf import settings


# garage_sale/models.py
class GarageSaleEvent(models.Model):
    location = models.ForeignKey(
        "core.Location",
        on_delete=models.PROTECT,
        related_name="garage_sale_events",
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_garage_sales",
    )

    consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_garage_sales",
    )

    title = models.CharField(max_length=140, blank=True, default="")
    start_date = models.DateField()
    end_date = models.DateField()

    def is_active_today(self):
        from django.utils import timezone
        today = timezone.localdate()
        return self.start_date <= today <= self.end_date


class SaleItem(models.Model):
    """
    An item listed for sale under a GarageSaleEvent.
    quantity_available decrements when customers confirm reservations.
    """
    event = models.ForeignKey(
        GarageSaleEvent,
        on_delete=models.CASCADE,
        related_name="items"
    )

    title = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    quantity_available = models.PositiveIntegerField(default=1)
    is_listed = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title", "id"]

    def __str__(self):
        return f"{self.title} (${self.price})"

    @property
    def is_available(self) -> bool:
        return self.is_listed and self.quantity_available > 0


class Reservation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        FULFILLED = "FULFILLED", "Fulfilled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PAID = "PAID", "Paid"

    event = models.ForeignKey(
        GarageSaleEvent,
        on_delete=models.CASCADE,
        related_name="reservations"
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="garage_sale_reservations",
        limit_choices_to={"role": "CUSTOMER"},
    )

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    assigned_consultant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="garage_sale_pickups",
        limit_choices_to={"role": "CONSULTANT"},
    )

    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reservation {self.id} - {self.customer} - {self.status}"


class ReservationItem(models.Model):
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name="lines"
    )

    item = models.ForeignKey(
        SaleItem,
        on_delete=models.PROTECT,
        related_name="reserved_lines"
    )

    quantity = models.PositiveIntegerField(default=1)
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ("reservation", "item")

    def __str__(self):
        return f"{self.item.title} x{self.quantity}"
