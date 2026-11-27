from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import ProfileSerializer, TeamMemberSerializer


class ProfileView(APIView):
    """
    GET/PATCH the authenticated user's own profile. There is
    deliberately no "list all users" or "edit any user" endpoint
    here — matches accounts.views.profile/profile_edit, which only
    ever read or write request.user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(ProfileSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TeamViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only list of colleagues at the same depot (or, for
    territory-level roles with no specific depot, the same
    territory) — mirrors accounts.views.team_list exactly.
    """

    serializer_class = TeamMemberSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.depot_id:
            return User.objects.filter(depot_id=user.depot_id).order_by("username")
        if user.territory_id:
            return User.objects.filter(territory_id=user.territory_id).order_by("username")
        return User.objects.none()
