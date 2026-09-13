import requests

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Subscription
from usage.services import current_month_usage, record_analysis_usage

from .models import AnalysisRecord
from .serializers import (
    CompactAnalysisRequestSerializer,
    CompactScannerRequestSerializer,
    DailyReportRequestSerializer,
)


def _get_subscription(user):
    sub, _ = Subscription.objects.get_or_create(
        user=user,
        defaults={
            "plan": settings.TDOS_DEFAULT_PLAN,
            "monthly_analysis_limit": settings.TDOS_DEFAULT_MONTHLY_LIMIT,
        },
    )
    return sub


def _account_error(user, sub):
    if not user.is_active or not sub.active:
        return Response(
            {"detail": "Account is inactive."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if sub.valid_until and sub.valid_until < timezone.now():
        return Response(
            {"detail": "Subscription has expired."},
            status=status.HTTP_403_FORBIDDEN,
        )

    return None


def _quota_error(user, sub, requested_units=1):
    used = current_month_usage(user)
    requested_units = max(1, int(requested_units or 1))

    if used + requested_units > sub.monthly_analysis_limit:
        return Response(
            {
                "detail": "Monthly analysis limit reached.",
                "usage": {
                    "used": used,
                    "requested": requested_units,
                    "limit": sub.monthly_analysis_limit,
                    "remaining": max(0, sub.monthly_analysis_limit - used),
                },
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    return None


def _internal_headers():
    return {
        "X-Internal-Service-Key": settings.FASTAPI_INTERNAL_KEY,
        "Content-Type": "application/json",
    }


def _post_fastapi(path, payload):
    url = f"{settings.FASTAPI_BASE_URL.rstrip('/')}{path}"

    try:
        upstream = requests.post(
            url,
            json=payload,
            headers=_internal_headers(),
            timeout=settings.FASTAPI_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return None, Response(
            {
                "detail": "Analytics service unavailable.",
                "error": str(exc),
                "upstream_url": url,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        body = upstream.json()
    except ValueError:
        return None, Response(
            {
                "detail": "Analytics service returned invalid JSON.",
                "status_code": upstream.status_code,
                "upstream_url": url,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if not upstream.ok:
        # Preserve the FastAPI status code/error so debugging remains easy.
        return None, Response(body, status=upstream.status_code)

    return body, None


def _unwrap_payload(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
        return payload["data"]
    return payload


def _extract_result_rows(payload):
    """
    Locate scanner-style result rows without forcing FastAPI to adopt a new
    response shape. Supports:
        {"data": {"results": [...]}}
        {"results": [...]}
        {"scanner_results": [...]}
        {"data": {"data": {"results": [...]}}}
    """
    data = _unwrap_payload(payload)

    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    if not isinstance(data, dict):
        return []

    rows = data.get("results") or data.get("scanner_results")

    if rows is None and isinstance(data.get("data"), dict):
        rows = data["data"].get("results")

    if not isinstance(rows, list):
        return []

    return [row for row in rows if isinstance(row, dict)]


def _save_analysis_rows(user, rows, source):
    """
    Store scanner/report rows in the same AnalysisRecord table used by the
    single-stock endpoint. Missing fields are tolerated.
    """
    for row in rows:
        ticker = str(row.get("ticker") or row.get("Ticker") or "").strip().upper()
        if not ticker:
            continue

        AnalysisRecord.objects.create(
            user=user,
            ticker=ticker,
            final_score=row.get("final_score", row.get("Final Score")),
            decision=str(row.get("decision", row.get("Decision", "")) or ""),
            setup_type=str(row.get("setup_type", row.get("Setup", "")) or ""),
            result=row,
        )


def _record_usage_for_tickers(user, tickers, source):
    for ticker in tickers:
        record_analysis_usage(
            user,
            ticker,
            metadata={"source": source},
        )


def _append_account(payload, sub, used_before, units):
    if not isinstance(payload, dict):
        return payload

    new_used = used_before + units
    payload["_account"] = {
        "plan": sub.plan,
        "usage_used": new_used,
        "usage_limit": sub.monthly_analysis_limit,
        "usage_remaining": max(0, sub.monthly_analysis_limit - new_used),
    }
    return payload


class CompactAnalysisProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CompactAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticker = (
            serializer.validated_data["ticker"]
            .strip()
            .upper()
            .replace(".", "-")
        )
        persist_signal = serializer.validated_data["persist_signal"]

        sub = _get_subscription(request.user)

        err = _account_error(request.user, sub)
        if err:
            return err

        err = _quota_error(request.user, sub, requested_units=1)
        if err:
            return err

        used = current_month_usage(request.user)

        payload, err = _post_fastapi(
            "/api/v1/analyze/compact",
            {
                "ticker": ticker,
                "persist_signal": persist_signal,
            },
        )
        if err:
            return err

        result = _unwrap_payload(payload)

        with transaction.atomic():
            AnalysisRecord.objects.create(
                user=request.user,
                ticker=ticker,
                final_score=result.get("final_score") if isinstance(result, dict) else None,
                decision=(result.get("decision") or "") if isinstance(result, dict) else "",
                setup_type=(result.get("setup_type") or "") if isinstance(result, dict) else "",
                result=result if isinstance(result, dict) else {"raw": result},
            )
            record_analysis_usage(
                request.user,
                ticker,
                metadata={"source": "django_proxy"},
            )

        payload = _append_account(payload, sub, used, 1)
        return Response(payload)


class CompactScannerProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CompactScannerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        values = dict(serializer.validated_data)
        tickers = values["tickers"][: values["max_names"]]
        values["tickers"] = tickers
        values["max_names"] = len(tickers)

        units = len(tickers)
        sub = _get_subscription(request.user)

        err = _account_error(request.user, sub)
        if err:
            return err

        err = _quota_error(request.user, sub, requested_units=units)
        if err:
            return err

        used = current_month_usage(request.user)

        payload, err = _post_fastapi(
            "/api/v1/scanner/compact",
            values,
        )
        if err:
            return err

        rows = _extract_result_rows(payload)

        with transaction.atomic():
            _save_analysis_rows(
                request.user,
                rows,
                source="django_scanner_proxy",
            )
            _record_usage_for_tickers(
                request.user,
                tickers,
                source="django_scanner_proxy",
            )

        payload = _append_account(payload, sub, used, units)
        return Response(payload)


class DailyReportProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DailyReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        values = dict(serializer.validated_data)
        tickers = values["tickers"][: values["max_names"]]
        values["tickers"] = tickers
        values["max_names"] = len(tickers)

        units = len(tickers)
        sub = _get_subscription(request.user)

        err = _account_error(request.user, sub)
        if err:
            return err

        err = _quota_error(request.user, sub, requested_units=units)
        if err:
            return err

        used = current_month_usage(request.user)

        payload, err = _post_fastapi(
            "/api/v1/report/daily",
            values,
        )
        if err:
            return err

        rows = _extract_result_rows(payload)

        with transaction.atomic():
            _save_analysis_rows(
                request.user,
                rows,
                source="django_daily_report_proxy",
            )
            _record_usage_for_tickers(
                request.user,
                tickers,
                source="django_daily_report_proxy",
            )

        payload = _append_account(payload, sub, used, units)
        return Response(payload)
