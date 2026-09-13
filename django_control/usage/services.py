from django.db.models import Sum
from django.utils import timezone
from .models import UsageEvent
def current_month_usage(user)->int:
    now=timezone.now()
    total=UsageEvent.objects.filter(user=user,event_type="analysis",created_at__year=now.year,created_at__month=now.month).aggregate(total=Sum("units")).get("total") or 0
    return int(total)
def record_analysis_usage(user,ticker:str,metadata=None):
    return UsageEvent.objects.create(user=user,event_type="analysis",ticker=(ticker or "").upper(),units=1,metadata=metadata or {})
