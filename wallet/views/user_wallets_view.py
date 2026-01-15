from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

# Local app imports
from ..models import Wallet

from ..serializers import *

import logging

logger = logging.getLogger(__name__)


class UserWalletsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        wallet_id = request.query_params.get("wallet_id", None)

        # GET ALL USER WALLETS
        wallets = Wallet.objects.filter(owner=user).order_by("created_at")

        # IF USER HAS NO WALLETS → FRONTEND SHOULD OPEN CREATE-WALLET MODAL
        if not wallets.exists():
            return Response({
                "requires_wallet": True,
                "detail": "User has no wallets."
            }, status=status.HTTP_200_OK)

        # SELECT WALLET
        if wallet_id:
            try:
                selected_wallet = wallets.get(id=wallet_id)
            except Wallet.DoesNotExist:
                return Response({"detail": "Wallet not found or not owned by user."},
                                status=status.HTTP_404_NOT_FOUND)
        else:
            selected_wallet = wallets.first()

        selected_wallet_data = WalletSerializer(selected_wallet).data

        # --- UPDATED: FULL WALLET DATA FOR OTHER WALLETS ---
        other_wallets_qs = wallets.exclude(id=selected_wallet.id)
        other_wallets = WalletSerializer(other_wallets_qs, many=True).data

        return Response({
            "selected_wallet": selected_wallet_data,
            "other_wallets": other_wallets
        }, status=status.HTTP_200_OK)
