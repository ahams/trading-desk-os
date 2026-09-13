from django.conf import settings
from django.db import models
class UsageEvent(models.Model):
    EVENT_CHOICES=[("analysis","Analysis"),("scan","Scan"),("other","Other")]
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="usage_events")
    event_type=models.CharField(max_length=20,choices=EVENT_CHOICES)
    ticker=models.CharField(max_length=32,blank=True)
    units=models.PositiveIntegerField(default=1)
    metadata=models.JSONField(default=dict,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes=[models.Index(fields=["user","created_at"]),models.Index(fields=["event_type","created_at"])]
    def __str__(self): return f"{self.user} · {self.event_type} · {self.created_at:%Y-%m-%d}"
