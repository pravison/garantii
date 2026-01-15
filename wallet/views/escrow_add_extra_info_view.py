from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from ..serializers import *

from wallet.models import EscrowAllocation

import logging

logger = logging.getLogger(__name__)


class EscrowAddExtraInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, escrow_id):
        """
        Add extra info/description to an escrow, only if description is empty.
        Only the payer (owner of payer_wallet) or staff can perform this.
        Accepts either 'extra' or 'extra_info' in JSON body.
        """
        payload_extra = request.data.get('extra') or request.data.get('extra_info') or ''
        extra_info = str(payload_extra).strip()
        if not extra_info:
            return Response({"detail": "extra info required"}, status=status.HTTP_400_BAD_REQUEST)

        escrow = get_object_or_404(EscrowAllocation, id=escrow_id)

        if not escrow.can_add_extra_by(request.user):
            return Response({"detail": "Not allowed to add info (already exists or not owner)"}, status=status.HTTP_403_FORBIDDEN)

        try:
            with transaction.atomic():
                updated = escrow.add_extra(extra_info, user=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({"detail": "Failed to save extra info"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = EscrowAllocationSerializer(updated)
        return Response({"detail": "Extra information added successfully", "transaction": serializer.data}, status=status.HTTP_200_OK)

