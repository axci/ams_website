from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("manager/", views.manager_dashboard, name="manager_dashboard"),
    path(
        "manager/client/<int:pk>/",
        views.manager_client_detail,
        name="manager_client_detail",
    ),
    path("change-password/", views.ChangePasswordView.as_view(), name="change_password"),
]
