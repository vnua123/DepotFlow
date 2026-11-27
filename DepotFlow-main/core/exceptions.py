"""
Shared DRF exception handler.

Almost every model in this project enforces its business rules in
clean()/save() via Django's full_clean(), which raises
django.core.exceptions.ValidationError — not DRF's own
ValidationError. A few service functions (e.g.
inventory.services.record_price_change,
inventory.services.create_adjustment) raise plain ValueError for the
same purpose. Left alone, DRF's default exception handler doesn't
know about either of these and turns them into unhandled 500s.

This handler translates both into a normal DRF 400 response so API
clients see the same validation messages a Django form/HTML view
would show, instead of a server error.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        else:
            detail = exc.messages
        return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, ValueError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return drf_exception_handler(exc, context)
