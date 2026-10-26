from django.urls import re_path

from . import views

app_name = "cml_exchange"

urlpatterns = [
    # Адрес работает и со слэшем на конце, и без: 1С не следует редиректам,
    # а APPEND_SLASH сломал бы POST-запросы с файлами.
    re_path(r"^exchange/?$", views.exchange, name="exchange"),
]
