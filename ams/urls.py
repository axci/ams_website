"""URL configuration for the ams project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.forms import LoginForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("tinymce/", include("tinymce.urls")),
    # Styled login view; remaining auth views (logout, password) from contrib.
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(authentication_form=LoginForm),
        name="login",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/", include("accounts.urls")),
    path("warehouse/", include("warehouses.urls")),
    path("news/", include("news.urls")),
    path("about/", include("about.urls")),
    path("", include("orders.urls")),
    path("", include("catalog.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Production fallback so uploaded media is served when there is no dedicated
    # file server in front (e.g. Railway). Under the docker-compose stack nginx
    # serves /media/ first, so this route is never reached there.
    from django.urls import re_path
    from django.views.static import serve as _media_serve

    urlpatterns += [
        re_path(
            rf"^{settings.MEDIA_URL.lstrip('/')}(?P<path>.*)$",
            _media_serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
