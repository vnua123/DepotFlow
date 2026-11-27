from django import forms
from django.forms import inlineformset_factory

from core.scoping import get_default_depot, get_visible_depots, is_unrestricted
from .models import Product, Supplier, StockReceipt, StockReceiptItem, Promotion


class ProductForm(forms.ModelForm):
    """
    base_cost_price/base_selling_price are deliberately excluded —
    they're a display-only cache. Use PriceChangeForm (which goes
    through inventory.services.record_price_change) to actually
    change pricing.
    """

    class Meta:
        model = Product
        fields = [
            "sku", "name", "category", "package_type",
            "volume", "pack_size", "is_active",
        ]


class PriceChangeForm(forms.Form):
    """
    Not a ModelForm — PriceHistory is append-only and must always
    be created through inventory.services.record_price_change(),
    never edited directly.
    """

    selling_price = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    cost_price = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False,
                                     help_text="Optional informational reference; leave blank to keep the current reference.")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "contact_person", "phone", "email", "address", "is_active"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if name.casefold() != "nbc":
            raise forms.ValidationError("NBC is the only supplier for new operational records. Existing historical supplier records are retained.")
        return "NBC"


class StockReceiptForm(forms.ModelForm):
    """
    invoice_number is excluded — auto-generated in StockReceipt.save().
    """

    class Meta:
        model = StockReceipt
        fields = ["supplier", "depot", "receipt_date"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # NBC is the only supplier for new operational receipts. Other supplier
        # rows are retained for historical records and reporting.
        self.fields["supplier"].queryset = Supplier.objects.filter(name__iexact="NBC", is_active=True)
        if user is not None:
            self.fields["depot"].queryset = get_visible_depots(user)
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()


StockReceiptItemFormSet = inlineformset_factory(
    StockReceipt,
    StockReceiptItem,
    fields=["product", "quantity", "cost_price", "rebate_landing_cost"],
    extra=1,
    can_delete=True,
)


class PromotionForm(forms.ModelForm):
    class Meta:
        model = Promotion
        fields = [
            "name", "level", "promotion_type", "description", "products",
            "supplier", "depot", "start_date", "end_date",
            "percentage_value", "fixed_value", "buy_quantity", "get_quantity",
            "minimum_quantity", "maximum_quantity", "is_active",
        ]
        widgets = {
            "products": forms.SelectMultiple(attrs={"size": 8}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is None:
            return

        self.fields["depot"].queryset = get_visible_depots(user)

        # A blank depot means a company-wide promotion. Only unrestricted
        # users may create/keep those; everyone else must pick (or is
        # auto-assigned) one of their own depots.
        if not is_unrestricted(user):
            self.fields["depot"].required = True
            self.fields["depot"].empty_label = None
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()