from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from ..serializers import *

import logging

logger = logging.getLogger(__name__)

class EscrowRequestReversalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, escrow_id):
        """
        Request a reversal for HELD escrow transaction.
        Only the payer (owner of payer_wallet) or staff can perform this.
        """
        escrow = get_object_or_404(EscrowAllocation, id=escrow_id)

        # permission check
        if not escrow.can_be_reversed_by(request.user):
            return Response({"detail": "Not allowed to reverse this escrow or invalid status"}, status=status.HTTP_403_FORBIDDEN)

        try:
            with transaction.atomic():
                updated = escrow.request_reversal(user=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": "Failed to request reversal"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = EscrowAllocationSerializer(updated)
        return Response({"detail": "Reversal requested successfully", "transaction": serializer.data}, status=status.HTTP_200_OK)

