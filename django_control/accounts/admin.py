from django.contrib import admin
from .models import Subscription
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display=("user","plan","monthly_analysis_limit","active","valid_until")
    list_filter=("plan","active")
    search_fields=("user__username","user__email")
