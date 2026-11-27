from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLog(TimeStampedModel):
    """
    Generic audit trail for important business changes across the
    whole project: price changes, promotion changes, inventory
    adjustments, financial reversals, and user permission changes
    (see project spec section 15).

    Prefer calling core.audit.log_action() rather than creating
    AuditLog rows directly, so every caller records the same shape
    of data.
    """

    class Action(models.TextChoices):
        PRICE_CHANGE = "PRICE_CHANGE", "Price Change"
        PROMOTION_CREATED = "PROMOTION_CREATED", "Promotion Created"
        PROMOTION_CHANGED = "PROMOTION_CHANGED", "Promotion Changed"
        INVENTORY_ADJUSTMENT = "INVENTORY_ADJUSTMENT", "Inventory Adjustment"
        FINANCE_REVERSAL = "FINANCE_REVERSAL", "Finance Reversal"
        PERMISSION_CHANGE = "PERMISSION_CHANGE", "Permission Change"
        OTHER = "OTHER", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )

    action = models.CharField(max_length=30, choices=Action.choices)

    # Generic link to whatever object was changed (Product,
    # Promotion, InventoryTransaction, Expense, User, ...).
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    # Snapshot of str(obj) at the time of logging, so the log stays
    # readable even if the object is later deleted.
    object_repr = models.CharField(max_length=255, blank=True)

    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    notes = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} - {self.object_repr} ({self.created_at:%Y-%m-%d %H:%M})"