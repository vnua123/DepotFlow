from django import forms
from django.forms import inlineformset_factory

from core.scoping import get_default_depot, get_visible_depots
from .models import Customer, Sale, SaleItem


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "outlet_type", "depot", "phone", "address", "is_active"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["depot"].queryset = get_visible_depots(user)
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()


class SaleForm(forms.ModelForm):
    """
    vehicle_load is deliberately excluded from the form fields — a
    sale is always created from a specific load's detail page, not
    picked in the form. It's set here in __init__ (not in the view
    after the fact) so Sale.clean()/save() can safely rely on
    self.vehicle_load during validation and salesman auto-fill.

    salesman is also excluded — Sale.save() auto-fills it from
    vehicle_load.salesman.
    """

    class Meta:
        model = Sale
        fields = ["customer", "sale_date", "notes"]

    def __init__(self, *args, vehicle_load=None, **kwargs):
        super().__init__(*args, **kwargs)
        if vehicle_load is not None:
            self.instance.vehicle_load = vehicle_load
            # Also limit the customer dropdown to this load's depot,
            # so users can't accidentally attach an unrelated outlet.
            self.fields["customer"].queryset = Customer.objects.filter(
                depot=vehicle_load.depot
            ) | Customer.objects.filter(depot__isnull=True)


SaleItemFormSet = inlineformset_factory(
    Sale,
    SaleItem,
    fields=["product", "quantity", "promotion"],
    extra=1,
    can_delete=True,
)