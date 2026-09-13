from rest_framework import serializers


class CompactAnalysisRequestSerializer(serializers.Serializer):
    ticker = serializers.CharField(max_length=32)
    persist_signal = serializers.BooleanField(default=True)


class CompactScannerRequestSerializer(serializers.Serializer):
    tickers = serializers.ListField(
        child=serializers.CharField(max_length=32),
        allow_empty=False,
        max_length=100,
    )
    max_names = serializers.IntegerField(min_value=1, max_value=100, default=20)
    include_options = serializers.BooleanField(default=False)
    compact = serializers.BooleanField(default=True)

    def validate_tickers(self, values):
        cleaned = []
        seen = set()
        for value in values:
            ticker = str(value).strip().upper().replace(".", "-")
            if ticker and ticker not in seen:
                seen.add(ticker)
                cleaned.append(ticker)
        if not cleaned:
            raise serializers.ValidationError("At least one valid ticker is required.")
        return cleaned


class DailyReportRequestSerializer(serializers.Serializer):
    tickers = serializers.ListField(
        child=serializers.CharField(max_length=32),
        allow_empty=False,
        max_length=100,
    )
    max_names = serializers.IntegerField(min_value=1, max_value=100, default=20)
    compact = serializers.BooleanField(default=True)

    # Kept optional so the Django proxy also works with the richer report
    # payload used by older TDOS frontends.
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    include_signal_records = serializers.BooleanField(required=False)

    def validate_tickers(self, values):
        cleaned = []
        seen = set()
        for value in values:
            ticker = str(value).strip().upper().replace(".", "-")
            if ticker and ticker not in seen:
                seen.add(ticker)
                cleaned.append(ticker)
        if not cleaned:
            raise serializers.ValidationError("At least one valid ticker is required.")
        return cleaned
