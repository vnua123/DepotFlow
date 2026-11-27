from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden

from .models import User
from .forms import ProfileForm, UserCreateForm
from .user_management import can_create_users


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def profile_edit(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    return render(request, "accounts/profile_form.html", {"form": form})


@login_required
def team_list(request):
    """
    Read-only view of colleagues at the same depot (or, for
    territory-level roles with no specific depot, the same
    territory). Role/permission changes are deliberately NOT
    editable here — that stays in Django admin.
    """
    if getattr(request.user, "role", "") == "DEPOT_OWNER":
        return HttpResponseForbidden("Depot Owners do not have access to team management.")

    if request.user.depot_id:
        colleagues = User.objects.filter(depot_id=request.user.depot_id).order_by("username")
    elif request.user.territory_id:
        colleagues = User.objects.filter(territory_id=request.user.territory_id).order_by("username")
    else:
        colleagues = User.objects.none()

    return render(request, "accounts/team_list.html", {
        "colleagues": colleagues,
        "can_create_users": can_create_users(request.user),
    })


@login_required
def user_create(request):
    """
    Create a user with a role below the current user's own. What each
    role may create is defined in accounts.user_management.
    """

    if not can_create_users(request.user):
        messages.error(request, "You do not have permission to create users.")
        return redirect("accounts:team_list")

    if request.method == "POST":
        form = UserCreateForm(request.POST, creator=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User '{user.username}' created.")
            return redirect("accounts:team_list")
    else:
        form = UserCreateForm(creator=request.user)

    return render(request, "accounts/user_form.html", {"form": form})
