from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from wallet.services import get_wallet_for_user

# Local app imports
from ..serializers import *
from wallet.models import EscrowAllocation

import logging

logger = logging.getLogger(__name__)


class WalletEscrowListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Returns all escrow transactions where the authenticated user is sender or receiver
        for the provided wallet_id. wallet_id can be wallet.pk or wallet.identifier.
        """
        wallet_id = request.GET.get('wallet_id')
        if not wallet_id:
            return Response({"detail": "wallet_id required"}, status=status.HTTP_400_BAD_REQUEST)

        wallet = get_wallet_for_user(wallet_id, request.user)
        if wallet is None:
            return Response({"detail": "Wallet not found or access denied"}, status=status.HTTP_404_NOT_FOUND)

        qs = EscrowAllocation.objects.filter(payer_wallet=wallet) | EscrowAllocation.objects.filter(receiver_wallet=wallet)
        qs = qs.order_by('-created_at')

        serializer = EscrowAllocationSerializer(qs, many=True)
        return Response({"transactions": serializer.data}, status=status.HTTP_200_OK)