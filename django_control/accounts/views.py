from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from usage.services import current_month_usage
from .models import Subscription
from .serializers import AccountSerializer
class AccountView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        sub,_=Subscription.objects.get_or_create(user=request.user,defaults={"plan":settings.TDOS_DEFAULT_PLAN,"monthly_analysis_limit":settings.TDOS_DEFAULT_MONTHLY_LIMIT})
        used=current_month_usage(request.user)
        return Response({"user":AccountSerializer(request.user).data,"usage":{"used":used,"limit":sub.monthly_analysis_limit,"remaining":max(0,sub.monthly_analysis_limit-used)}})
