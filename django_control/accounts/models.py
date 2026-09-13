from django.conf import settings
from django.db import models
class Subscription(models.Model):
    PLAN_CHOICES=[("owner","Owner"),("beta","Beta"),("free","Free"),("pro","Pro"),("desk","Desk")]
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="subscription")
    plan=models.CharField(max_length=20,choices=PLAN_CHOICES,default="beta")
    monthly_analysis_limit=models.PositiveIntegerField(default=500)
    active=models.BooleanField(default=True)
    valid_until=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def __str__(self): return f"{self.user} · {self.plan}"
