from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import ProfileView, TeamViewSet

router = DefaultRouter()
router.register("team", TeamViewSet, basename="team")

urlpatterns = [
    path("profile/", ProfileView.as_view(), name="api-profile"),
] + router.urls
