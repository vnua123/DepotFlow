from django import forms
from core.scoping import get_visible_depots, get_default_depot
from .models import MonthlyHealthCheck

class MonthlyHealthCheckForm(forms.ModelForm):
    class Meta:
        model = MonthlyHealthCheck
        fields = ['depot', 'year', 'month', 'grand_total_stock_cases', 'grand_total_stock_value', 'cash_at_hand', 'git_order_released_cases', 'git_order_released', 'credit_exposure_balance', 'nbc_credit_limit', 'nbc_permanent_credit', 'empties_quantity', 'plastic_quantity', 'empties_value', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['depot'].queryset = get_visible_depots(user)
            default = get_default_depot(user)
            if default:
                self.fields['depot'].initial = default.pk
                self.fields['depot'].widget = forms.HiddenInput()


from .models import MonthlyProfitability


class MonthlyProfitabilityForm(forms.ModelForm):
    class Meta:
        model = MonthlyProfitability
        fields = ['depot', 'year', 'month', 'target_reinvestment_percent', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}
        labels = {
            'target_reinvestment_percent': 'Required reinvestment percentage of monthly net profit',
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['depot'].queryset = get_visible_depots(user)
            default = get_default_depot(user)
            if default:
                self.fields['depot'].initial = default.pk
                self.fields['depot'].widget = forms.HiddenInput()
        self.fields['target_reinvestment_percent'].help_text = 'For example, 20 means the month-end working-capital increase should be at least 20% of positive net profit.'
