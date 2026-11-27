from rest_framework.routers import DefaultRouter

from .api import (
    ExpenseCategoryViewSet, BusinessLedgerViewSet,
    ExpenseViewSet, SupplierPaymentViewSet, SupplierRebateViewSet,
)

router = DefaultRouter()
router.register("expense-categories", ExpenseCategoryViewSet, basename="expensecategory")
router.register("expenses", ExpenseViewSet, basename="expense")
router.register("supplier-payments", SupplierPaymentViewSet, basename="supplierpayment")
router.register("supplier-rebates", SupplierRebateViewSet, basename="supplierrebate")
router.register("ledger", BusinessLedgerViewSet, basename="businessledger")

urlpatterns = router.urls
