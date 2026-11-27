from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.forms import inlineformset_factory

from core.scoping import get_default_depot, get_visible_depots
from .models import (
    Vehicle, VehicleSalesman, VehicleLoad, VehicleLoadItem,
    VehicleReturn, VehicleReturnItem, SalesTarget,
)

User = get_user_model()


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ["depot", "registration_number", "vehicle_name", "capacity", "is_active"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["depot"].queryset = get_visible_depots(user)
            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()


class VehicleReassignForm(forms.Form):
    """
    Shown when deleting a vehicle that's still assigned to one or
    more salesmen (and has no load history of its own, which would
    block deletion outright regardless). One row per affected
    salesman — each picks either an existing other vehicle or fills
    in a new one, mirroring VehicleSalesmanForm's inline-creation
    pattern. Submitting reassigns every salesman, then deletes the
    original vehicle.
    """

    def __init__(self, *args, vehicle=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehicle = vehicle
        self._row_meta = []

        select_attrs = {"class": "w-full rounded border border-stone-300 text-sm px-2 py-1.5"}
        text_attrs = {"class": "w-full rounded border border-stone-300 text-sm px-2 py-1.5"}
        number_attrs = {"class": "w-24 rounded border border-stone-300 text-sm px-2 py-1.5"}

        other_vehicles = Vehicle.objects.exclude(pk=vehicle.pk)
        if user is not None:
            other_vehicles = other_vehicles.filter(depot__in=get_visible_depots(user))
        other_vehicles = other_vehicles.order_by("registration_number")

        for salesman in VehicleSalesman.objects.filter(vehicle=vehicle).order_by("name"):
            existing_name = f"existing_vehicle_{salesman.id}"
            new_reg_name = f"new_registration_{salesman.id}"
            new_label_name = f"new_name_{salesman.id}"
            new_capacity_name = f"new_capacity_{salesman.id}"

            self.fields[existing_name] = forms.ModelChoiceField(
                queryset=other_vehicles, required=False, label="Existing vehicle",
                empty_label="— choose an existing vehicle —",
                widget=forms.Select(attrs=select_attrs),
            )
            self.fields[new_reg_name] = forms.CharField(
                max_length=30, required=False, label="Or new registration number",
                widget=forms.TextInput(attrs={**text_attrs, "placeholder": "Registration no."}),
            )
            self.fields[new_label_name] = forms.CharField(
                max_length=100, required=False, label="New vehicle name",
                widget=forms.TextInput(attrs={**text_attrs, "placeholder": "Vehicle name"}),
            )
            self.fields[new_capacity_name] = forms.IntegerField(
                required=False, min_value=0, label="New vehicle capacity",
                widget=forms.NumberInput(attrs={**number_attrs, "placeholder": "Capacity"}),
            )

            self._row_meta.append({
                "salesman": salesman,
                "existing_name": existing_name,
                "new_reg_name": new_reg_name,
                "new_label_name": new_label_name,
                "new_capacity_name": new_capacity_name,
            })

    @property
    def rows(self):
        return [
            {
                "salesman": meta["salesman"],
                "existing": self[meta["existing_name"]],
                "new_registration": self[meta["new_reg_name"]],
                "new_name": self[meta["new_label_name"]],
                "new_capacity": self[meta["new_capacity_name"]],
            }
            for meta in self._row_meta
        ]

    def clean(self):
        cleaned_data = super().clean()

        for meta in self._row_meta:
            existing = cleaned_data.get(meta["existing_name"])
            new_reg = cleaned_data.get(meta["new_reg_name"])

            if existing and new_reg:
                self.add_error(
                    meta["existing_name"],
                    "Choose either an existing vehicle or fill in a new one, not both.",
                )
            elif not existing and not new_reg:
                self.add_error(
                    meta["existing_name"],
                    "Pick an existing vehicle, or fill in a new registration number, for this salesman.",
                )
            elif new_reg and Vehicle.objects.filter(registration_number=new_reg).exists():
                self.add_error(meta["new_reg_name"], "This registration number is already in use.")

        return cleaned_data

    def get_assignments(self):
        """
        One dict per affected salesman: either {"salesman", "vehicle"}
        for an existing pick, or {"salesman", "new_vehicle_data"} for
        a brand-new vehicle to create (same depot as the one being
        deleted).
        """

        results = []

        for meta in self._row_meta:
            existing = self.cleaned_data.get(meta["existing_name"])

            if existing:
                results.append({"salesman": meta["salesman"], "vehicle": existing, "new_vehicle_data": None})
            else:
                results.append({
                    "salesman": meta["salesman"],
                    "vehicle": None,
                    "new_vehicle_data": {
                        "depot": self.vehicle.depot,
                        "registration_number": self.cleaned_data.get(meta["new_reg_name"]),
                        "vehicle_name": self.cleaned_data.get(meta["new_label_name"]) or "",
                        "capacity": self.cleaned_data.get(meta["new_capacity_name"]) or 0,
                    },
                })

        return results


class VehicleSalesmanForm(forms.ModelForm):
    """
    Also creates the salesman's login account in the same step —
    username/password below aren't VehicleSalesman fields, they
    create a linked User (role=SALESMAN) via save().

    If this salesman already has a login (editing an existing one),
    the username/password fields are optional and left blank by
    default — submitting them blank leaves the existing login
    untouched. A legacy salesman with no login yet can still have
    one added by filling these in on an edit.
    """

    username = forms.CharField(
        max_length=150,
        required=False,
        help_text="This salesman will log in with this username.",
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput,
        required=False,
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput,
        required=False,
    )

    class Meta:
        model = VehicleSalesman
        fields = ["name", "employee_id", "phone", "depot", "vehicle", "is_active"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user is not None:
            visible_depots = get_visible_depots(user)
            self.fields["depot"].queryset = visible_depots

            visible_vehicles = Vehicle.objects.filter(depot__in=visible_depots)
            self.fields["vehicle"].queryset = visible_vehicles

            default_depot = get_default_depot(user)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].widget = forms.HiddenInput()

            single_vehicle = list(visible_vehicles[:2])
            if len(single_vehicle) == 1:
                self.fields["vehicle"].initial = single_vehicle[0].pk
                self.fields["vehicle"].widget = forms.HiddenInput()

        self._needs_login = not (self.instance.pk and self.instance.user_id)

        if self._needs_login:
            self.fields["username"].required = True
            self.fields["password1"].required = True
            self.fields["password2"].required = True

    def clean_username(self):
        username = self.cleaned_data.get("username")

        if username:
            existing = User.objects.filter(username=username)
            if self.instance.user_id:
                existing = existing.exclude(pk=self.instance.user_id)
            if existing.exists():
                raise forms.ValidationError("This username is already taken.")

        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Passwords do not match.")
            else:
                try:
                    validate_password(password1)
                except DjangoValidationError as exc:
                    self.add_error("password1", exc)

        return cleaned_data

    def save(self, commit=True):
        salesman = super().save(commit=commit)

        username = self.cleaned_data.get("username")
        password1 = self.cleaned_data.get("password1")

        if commit and username and password1:
            user = User.objects.create_user(
                username=username,
                password=password1,
                role=User.Role.SALESMAN,
                depot=salesman.depot,
                first_name=salesman.name,
            )
            salesman.user = user
            salesman.save(update_fields=["user"])

        return salesman


class LoadCloseForm(forms.Form):
    """
    Captures the day's result for every product on a load in one
    step — how many units were sold and how many were returned —
    built fresh from VehicleLoad.reconciliation_status() so the
    "remaining" figure always reflects what's actually still
    outstanding right now.

    Submitting this creates a single Sale (with one SaleItem per
    product sold, customer left blank — this flow doesn't track
    per-customer detail) and/or a single VehicleReturn (with one
    item per product returned), then closes the load. See
    operations.views.load_close.
    """

    def __init__(self, *args, load=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.load = load
        self._row_meta = []

        number_attrs = {"class": "w-20 rounded border border-stone-300 text-sm px-2 py-1"}
        select_attrs = {"class": "rounded border border-stone-300 text-sm px-2 py-1"}

        for row in load.reconciliation_status():
            product = row["product"]
            remaining = row["remaining"]

            sold_name = f"sold_{product.id}"
            returned_name = f"returned_{product.id}"
            condition_name = f"condition_{product.id}"

            self.fields[sold_name] = forms.IntegerField(
                min_value=0, initial=max(remaining, 0),
                widget=forms.NumberInput(attrs=number_attrs),
            )
            self.fields[returned_name] = forms.IntegerField(
                min_value=0, initial=0,
                widget=forms.NumberInput(attrs=number_attrs),
            )
            self.fields[condition_name] = forms.ChoiceField(
                choices=[("GOOD", "Good"), ("DAMAGED", "Damaged")],
                initial="GOOD", required=False,
                widget=forms.Select(attrs=select_attrs),
            )

            self._row_meta.append({
                "product": product,
                "loaded": row["loaded"],
                "remaining": remaining,
                "sold_name": sold_name,
                "returned_name": returned_name,
                "condition_name": condition_name,
            })

    @property
    def rows(self):
        """Bound fields for template rendering, one row per product."""
        return [
            {
                "product": meta["product"],
                "loaded": meta["loaded"],
                "remaining": meta["remaining"],
                "sold": self[meta["sold_name"]],
                "returned": self[meta["returned_name"]],
                "condition": self[meta["condition_name"]],
            }
            for meta in self._row_meta
        ]

    def clean(self):
        cleaned_data = super().clean()

        for meta in self._row_meta:
            sold = cleaned_data.get(meta["sold_name"])
            returned = cleaned_data.get(meta["returned_name"])

            if sold is None or returned is None:
                continue

            if sold + returned != meta["remaining"]:
                self.add_error(
                    meta["sold_name"],
                    f"Sold + returned must add up to {meta['remaining']} "
                    f"(what's still unaccounted for) — got {sold + returned}."
                )

        return cleaned_data

    def get_results(self):
        """Rows with any activity, as plain dicts — skips products left untouched (0 sold, 0 returned)."""
        results = []

        for meta in self._row_meta:
            sold = self.cleaned_data.get(meta["sold_name"], 0)
            returned = self.cleaned_data.get(meta["returned_name"], 0)
            condition = self.cleaned_data.get(meta["condition_name"]) or "GOOD"

            if sold or returned:
                results.append({
                    "product": meta["product"],
                    "sold": sold,
                    "returned": returned,
                    "condition": condition,
                })

        return results


class SalesTargetForm(forms.ModelForm):
    class Meta:
        model = SalesTarget
        fields = ["salesman", "year", "month", "target_quantity"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["salesman"].queryset = VehicleSalesman.objects.filter(
                depot__in=get_visible_depots(user)
            )


class VehicleLoadForm(forms.ModelForm):
    """
    Only salesman is picked here — vehicle and depot are both
    derived automatically from that salesman's own assignment
    (VehicleSalesman.vehicle/.depot in clean() below), since every
    salesman is already tied to exactly one vehicle and one depot;
    asking the user to separately re-pick vehicle/depot after
    picking the salesman was pure redundancy. load_number is
    excluded — auto-generated in VehicleLoad.save(). load_date is
    excluded too — always today (the model's default), never
    user-editable, so a load's date can't be backdated or
    forward-dated. This is also what makes the "same-day reload"
    rule in VehicleLoad.clean() reliable: every load a user creates
    is dated today, full stop.
    """

    class Meta:
        model = VehicleLoad
        fields = ["salesman", "notes"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["salesman"].queryset = VehicleSalesman.objects.filter(
                depot__in=get_visible_depots(user)
            )

    def clean(self):
        cleaned_data = super().clean()
        salesman = cleaned_data.get("salesman")

        if salesman is not None:
            if salesman.vehicle_id is None:
                self.add_error(
                    "salesman",
                    f"{salesman.name} has no vehicle assigned yet — assign one on "
                    "the Salesmen page before creating a load for them.",
                )
            else:
                self.instance.vehicle = salesman.vehicle

            self.instance.depot = salesman.depot

        return cleaned_data


VehicleLoadItemFormSet = inlineformset_factory(
    VehicleLoad,
    VehicleLoadItem,
    fields=["product", "quantity", "promo_discount"],
    extra=1,
    can_delete=True,
)


class VehicleReturnForm(forms.ModelForm):
    """
    vehicle_load is deliberately excluded from the form fields — a
    return is always created from a specific load's detail page,
    not picked in the form. It's set here in __init__ (not in the
    view after the fact) so VehicleReturn.clean() can safely access
    self.vehicle_load during validation.

    return_number is excluded too — auto-generated in VehicleReturn.save().
    """

    class Meta:
        model = VehicleReturn
        fields = ["return_date", "notes"]

    def __init__(self, *args, vehicle_load=None, **kwargs):
        super().__init__(*args, **kwargs)
        if vehicle_load is not None:
            self.instance.vehicle_load = vehicle_load


VehicleReturnItemFormSet = inlineformset_factory(
    VehicleReturn,
    VehicleReturnItem,
    fields=["product", "quantity", "condition", "notes"],
    extra=1,
    can_delete=True,
)