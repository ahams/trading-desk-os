from django.contrib import admin
from .models import AnalysisRecord
@admin.register(AnalysisRecord)
class AnalysisRecordAdmin(admin.ModelAdmin):
    list_display=("ticker","user","final_score","decision","created_at")
    list_filter=("decision","created_at")
    search_fields=("ticker","user__username","user__email")
    readonly_fields=("created_at",)
