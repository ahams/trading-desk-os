from django.contrib import admin
from django.urls import include, path

from research.views import CompactScannerProxyView, DailyReportProxyView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/account/", include("accounts.account_urls")),
    path("api/analysis/", include("research.urls")),

    # Streamlit / Swift-facing Django JWT proxy endpoints.
    path(
        "api/scanner/compact/",
        CompactScannerProxyView.as_view(),
        name="scanner-compact",
    ),
    path(
        "api/report/daily/",
        DailyReportProxyView.as_view(),
        name="report-daily",
    ),
]
