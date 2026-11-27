"""
Shared helper for writing AuditLog entries.

Call log_action() from the specific sanctioned mutation points that
matter (see project spec section 15) rather than creating AuditLog
rows directly, so every caller records data in the same shape.
"""

from django.contrib.contenttypes.models import ContentType

from core.models import AuditLog


def log_action(action, obj=None, user=None, old_value=None, new_value=None, notes="", request=None):
    content_type = None
    object_id = None
    object_repr = ""

    if obj is not None:
        content_type = ContentType.objects.get_for_model(obj)
        object_id = obj.pk
        object_repr = str(obj)[:255]

    ip_address = None
    user_agent = ""

    if request is not None:
        ip_address = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        if user is None and getattr(request, "user", None) is not None and request.user.is_authenticated:
            user = request.user

    return AuditLog.objects.create(
        user=user,
        action=action,
        content_type=content_type,
        object_id=object_id,
        object_repr=object_repr,
        old_value=old_value,
        new_value=new_value,
        notes=notes,
        ip_address=ip_address,
        user_agent=user_agent,
    )