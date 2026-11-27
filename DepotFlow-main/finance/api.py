from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import role_permission
from core.scoping import get_visible_depots
from .models import ExpenseCategory, BusinessLedger, Expense, SupplierPayment, SupplierRebate
from .serializers import (
    ExpenseCategorySerializer, BusinessLedgerSerializer,
    ExpenseSerializer, SupplierPaymentSerializer, SupplierRebateSerializer,
    ReversalSerializer,
)

# Matches finance.views._can_record_expenses.
_RECORD_EXPENSE_ROLES = ("SUPER_ADMIN", "DEPOT_OWNER", "DEPOT_MANAGER", "DEPOT_OFFICER")
# Matches finance.views._can_approve_finance.
_APPROVE_FINANCE_ROLES = ("SUPER_ADMIN", "DEPOT_OWNER", "DEPOT_MANAGER", "FINANCE_OFFICER")
# Supplier rebates deliberately remain unavailable to Depot Owner.
_REBATE_ROLES = ("SUPER_ADMIN", "DEPOT_MANAGER", "FINANCE_OFFICER")


class ExpenseCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    No HTML page manages these either — they're admin-only lookup
    data. Exposed read-only here so API clients can populate an
    expense form's category choices.
    """

    queryset = ExpenseCategory.objects.all().order_by("name")
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated]


class BusinessLedgerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Scoped the same way as finance.views.ledger_list: Super Admin
    sees every depot, Territory Manager sees their own territory,
    everyone else only their own depot — a deliberate exception to
    most other read-only viewsets here, since ledger entries are
    real financial detail for a specific depot.
    """

    serializer_class = BusinessLedgerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return BusinessLedger.objects.filter(
            depot__in=get_visible_depots(self.request.user)
        ).select_related("depot").order_by("-transaction_date", "-created_at")


class ExpenseViewSet(viewsets.ModelViewSet):
    """
    No PUT/PATCH/DELETE: an Expense's financial substance is locked
    after creation (LedgerPostedRecord._check_locked_fields_unchanged)
    and the only sanctioned edits are the approve/reverse actions
    below — matches finance.views, which likewise never exposes a
    generic edit or delete page for Expense.
    """

    serializer_class = ExpenseSerializer
    permission_classes = [role_permission(*_RECORD_EXPENSE_ROLES)]
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        # Reading is available to every authenticated user and remains
        # depot-scoped by get_queryset(); creating stays on the stricter
        # expense-recording role set. approve/reverse use their decorators.
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        return Expense.objects.filter(
            depot__in=get_visible_depots(self.request.user)
        ).select_related("depot", "category").order_by("-expense_date", "-created_at")

    @action(detail=True, methods=["post"], permission_classes=[role_permission(*_APPROVE_FINANCE_ROLES)])
    def approve(self, request, pk=None):
        expense = self.get_object()
        expense.approved = True
        expense.save(update_fields=["approved", "updated_at"])
        return Response(ExpenseSerializer(expense).data)

    @action(detail=True, methods=["post"], permission_classes=[role_permission(*_APPROVE_FINANCE_ROLES)])
    def reverse(self, request, pk=None):
        expense = self.get_object()
        serializer = ReversalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expense.reverse(user=request.user, reason=serializer.validated_data["reason"])
        return Response(ExpenseSerializer(expense).data)


class SupplierPaymentViewSet(viewsets.ModelViewSet):
    """No PUT/PATCH/DELETE — see ExpenseViewSet docstring; reverse() is the only correction path."""

    serializer_class = SupplierPaymentSerializer
    permission_classes = [role_permission(*_APPROVE_FINANCE_ROLES)]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            SupplierPayment.objects
            .filter(depot__in=get_visible_depots(self.request.user))
            .select_related("depot", "supplier", "stock_receipt")
            .order_by("-payment_date", "-created_at")
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payment = self.get_object()
        serializer = ReversalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment.reverse(user=request.user, reason=serializer.validated_data["reason"])
        return Response(SupplierPaymentSerializer(payment).data)


class SupplierRebateViewSet(viewsets.ModelViewSet):
    """No PUT/PATCH/DELETE — see ExpenseViewSet docstring; reverse() is the only correction path."""

    serializer_class = SupplierRebateSerializer
    permission_classes = [role_permission(*_REBATE_ROLES)]
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        return SupplierRebate.objects.filter(
            depot__in=get_visible_depots(self.request.user)
        ).select_related("depot", "supplier").order_by("-rebate_date", "-created_at")

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        rebate = self.get_object()
        serializer = ReversalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rebate.reverse(user=request.user, reason=serializer.validated_data["reason"])
        return Response(SupplierRebateSerializer(rebate).data)
