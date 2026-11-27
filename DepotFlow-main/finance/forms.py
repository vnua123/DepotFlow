from django import forms

from core.scoping import get_default_depot, get_visible_depots
from .models import Expense, SupplierPayment, SupplierRebate


class ExpenseForm(forms.ModelForm):
    """
    reference_number is auto-generated in Expense.save(). approved/
    is_reversed/reversed_* are workflow/locked fields, never set at
    creation time through this form.
    """

    class Meta:
        model = Expense
        fields = ["depot", "category", "expense_date", "description", "amount", "payment_method"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["depot"].queryset = get_visible_depots(user)
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()


class SupplierPaymentForm(forms.ModelForm):
    class Meta:
        model = SupplierPayment
        fields = ["depot", "supplier", "stock_receipt", "payment_date", "amount", "notes"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = self.fields["supplier"].queryset.filter(name__iexact="NBC")
        if user is not None:
            self.fields["depot"].queryset = get_visible_depots(user)
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()


class SupplierRebateForm(forms.ModelForm):
    class Meta:
        model = SupplierRebate
        fields = ["depot", "supplier", "rebate_date", "amount", "description"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = self.fields["supplier"].queryset.filter(name__iexact="NBC")
        if user is not None:
            self.fields["depot"].queryset = get_visible_depots(user)
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()


class ReversalForm(forms.Form):
    """
    Not a ModelForm — reversal is always performed through
    LedgerPostedRecord.reverse(), never a direct field edit.
    """

    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        required=True,
        help_text="Required — explain why this record is being reversed.",
    )

class ExpenseImportForm(forms.Form):
    """Step 1 of the Excel import: which file, which depot, how to record it."""

    depot = forms.ModelChoiceField(queryset=None)
    file = forms.FileField(label="Expense workbook (.xlsx)")
    sheet_name = forms.CharField(
        required=False,
        label="Sheet name (optional)",
        help_text='Leave blank to use the sheet called "Expense".',
    )
    payment_method = forms.ChoiceField(
        choices=Expense.PaymentMethod.choices,
        initial=Expense.PaymentMethod.CASH,
        help_text="The sheet does not record how each expense was paid, so every imported expense gets this.",
    )
    mark_approved = forms.BooleanField(
        required=False,
        label="Mark the imported expenses as approved",
        help_text="Leave unticked to review them first; they can be approved all at once afterwards.",
    )

    def __init__(self, *args, user=None, can_approve=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["depot"].queryset = get_visible_depots(user)
        default_depot = get_default_depot(user)
        if default_depot is not None:
            self.fields["depot"].initial = default_depot.pk
            self.fields["depot"].widget = forms.HiddenInput()
        if not can_approve:
            del self.fields["mark_approved"]

    def clean_file(self):
        from .expense_import import MAX_UPLOAD_BYTES

        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError("Upload an Excel workbook (.xlsx).")
        if upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("That file is larger than 10 MB.")
        return upload
