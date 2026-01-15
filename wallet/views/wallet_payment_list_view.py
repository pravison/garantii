from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

# Local app imports
from ..models import *
from ..serializers import *

import logging

logger = logging.getLogger(__name__)

class WalletPaymentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet_id = request.GET.get("wallet_id")

        if not wallet_id:
            return Response({"detail": "wallet_id required"}, status=400)

        qs = PaymentTransaction.objects.filter(wallet_id=wallet_id)

        serializer = PaymentTransactionSerializer(qs, many=True)
        return Response({"transactions": serializer.data})