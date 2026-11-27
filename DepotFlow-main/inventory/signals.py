from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from inventory.models import Promotion


_PROMOTION_TRACKED_FIELDS = [
    "name", "level", "promotion_type", "start_date", "end_date",
    "percentage_value", "fixed_value", "buy_quantity", "get_quantity",
    "minimum_quantity", "maximum_quantity", "is_active",
]


def _promotion_snapshot(instance):
    return {field: str(getattr(instance, field)) for field in _PROMOTION_TRACKED_FIELDS}


@receiver(pre_save, sender=Promotion)
def capture_promotion_before_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._pre_save_snapshot = _promotion_snapshot(sender.objects.get(pk=instance.pk))
        except sender.DoesNotExist:
            instance._pre_save_snapshot = None
    else:
        instance._pre_save_snapshot = None


@receiver(post_save, sender=Promotion)
def log_promotion_change(sender, instance, created, **kwargs):
    from core.audit import log_action
    from core.models import AuditLog

    if created:
        log_action(
            AuditLog.Action.PROMOTION_CREATED,
            obj=instance,
            user=instance.created_by,
            new_value=_promotion_snapshot(instance),
        )
        return

    old_snapshot = getattr(instance, "_pre_save_snapshot", None)
    new_snapshot = _promotion_snapshot(instance)

    if old_snapshot is not None and old_snapshot != new_snapshot:
        log_action(
            AuditLog.Action.PROMOTION_CHANGED,
            obj=instance,
            old_value=old_snapshot,
            new_value=new_snapshot,
        )