from django.conf import settings
from django.db import models
class AnalysisRecord(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="analyses")
    ticker=models.CharField(max_length=32,db_index=True)
    final_score=models.FloatField(null=True,blank=True)
    decision=models.CharField(max_length=100,blank=True)
    setup_type=models.CharField(max_length=255,blank=True)
    result=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True,db_index=True)
    class Meta:
        ordering=["-created_at"]
        indexes=[models.Index(fields=["user","created_at"]),models.Index(fields=["ticker","created_at"])]
    def __str__(self): return f"{self.ticker} · {self.user} · {self.created_at:%Y-%m-%d %H:%M}"
