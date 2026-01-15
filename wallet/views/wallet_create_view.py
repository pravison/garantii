import random
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from ..models import *
from ..serializers import *

# Utilities
from account.utils import format_kenyan_phone_number

import logging

logger = logging.getLogger(__name__)

class WalletCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        identifier = request.data.get('identifier')
        is_business = request.data.get('is_business', False)

        # PERSONAL WALLET VALIDATION
        if not is_business:
            phone_number = format_kenyan_phone_number(identifier)
            if not phone_number:
                return Response({"detail": "Invalid phone number for personal wallet."},
                                status=status.HTTP_400_BAD_REQUEST)

            if Wallet.objects.filter(identifier=phone_number).exists():
                return Response({"detail": "Wallet with this phone already exists."},
                                status=status.HTTP_400_BAD_REQUEST)

            identifier = phone_number

        # BUSINESS WALLET — ensure unique
        else:
            while Wallet.objects.filter(identifier=identifier).exists():
                identifier = str(random.randint(100000, 999999))

        wallet = Wallet.objects.create(
            owner=user,
            identifier=identifier,
            is_business=is_business
        )

        serializer = WalletCreateSerializer(wallet)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

