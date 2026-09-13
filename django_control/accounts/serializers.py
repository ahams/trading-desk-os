from django.contrib.auth.models import User
from rest_framework import serializers
from .models import Subscription
class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model=Subscription
        fields=("plan","monthly_analysis_limit","active","valid_until")
class AccountSerializer(serializers.ModelSerializer):
    subscription=SubscriptionSerializer(read_only=True)
    class Meta:
        model=User
        fields=("id","username","email","first_name","last_name","is_active","subscription")
