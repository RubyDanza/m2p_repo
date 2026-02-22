from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),

    # Catch Django default auth urls (fallback)
    path("accounts/", include("django.contrib.auth.urls")),

    # Core (MFP landing + auth)
    path("", include(("core.urls", "core"), namespace="core")),

    # Businesses
    path("physio/", include(("physio.urls", "physio"), namespace="physio")),
    path("garage-sale/", include(("garage_sale.urls", "garage_sale"), namespace="garage_sale")),
    path("accounts/", include("django.contrib.auth.urls")),

]

