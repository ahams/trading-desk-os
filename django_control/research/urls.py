from django.urls import path

from .views import CompactAnalysisProxyView

urlpatterns = [
    path("compact/", CompactAnalysisProxyView.as_view(), name="analysis-compact"),
]
