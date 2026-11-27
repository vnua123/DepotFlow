from django import forms

from .models import Territory, Depot


class TerritoryForm(forms.ModelForm):
    class Meta:
        model = Territory
        fields = ["name"]


class DepotForm(forms.ModelForm):
    initial_nbc_category = forms.ChoiceField(choices=[('', 'Do not assign now'), ('STANDARD', 'Standard'), ('MAXI', 'Maxi'), ('MEGA', 'Mega')], required=False, label='Initial NBC placement')
    initial_nbc_reason = forms.CharField(required=False, max_length=500, label='Reason for initial NBC placement', widget=forms.TextInput(attrs={'placeholder': 'Required only when an initial category is selected'}))
    class Meta:
        model = Depot
        fields = ["territory", "name", "code", "address"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        role = getattr(user, "role", "") if user else ""
        if self.instance and self.instance.pk:
            self.fields.pop('initial_nbc_category', None)
            self.fields.pop('initial_nbc_reason', None)

        # Commercial Managers can only assign a depot to their own
        # territory. This is enforced at form level as well as in views.
        if role == "TERRITORY_MANAGER":
            if getattr(user, "territory_id", None):
                self.fields["territory"].queryset = Territory.objects.filter(
                    pk=user.territory_id
                )
                self.fields["territory"].initial = user.territory_id
            else:
                self.fields["territory"].queryset = Territory.objects.none()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('initial_nbc_category') and not (cleaned.get('initial_nbc_reason') or '').strip():
            self.add_error('initial_nbc_reason', 'Provide a reason when assigning an initial placement.')
        return cleaned
