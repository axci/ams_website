from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("change-password/", views.ChangePasswordView.as_view(), name="change_password"),
]
