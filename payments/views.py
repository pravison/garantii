from django.shortcuts import render


from rest_framework.views import APIView
from rest_framework.response import Response

from wallet.models import Wallet
from payments.utils import identify_account_number
from payments.get_customer_order import get_order_allocations

from payments.services.mpesa_parser import MpesaC2BParser
from wallet.escrow_processor import EscrowProcessor
from wallet.models import FailedMpesaTransaction
import logging

logger = logging.getLogger(__name__)


# mpesa validation.py 
class MpesaC2BValidationView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = request.data

        bill_ref = data.get("BillRefNumber")
        acct_type = identify_account_number(bill_ref)

        try:
            if acct_type == "BUSINESS_TILL":
                Wallet.objects.only("id").get(identifier=bill_ref, is_business=True)

            elif acct_type == "ORDER":
                get_order_allocations(bill_ref)

            elif acct_type == "PHONE":
                pass

            else:
                raise ValueError("Invalid account")

        except Exception:
            return Response({"ResultCode": 1, "ResultDesc": "Rejected"})

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

# mpesa/views/c2b_confirmation.py



class MpesaC2BConfirmationView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        txn = None  # 👈 IMPORTANT

        try:
            txn = MpesaC2BParser.parse_confirmation(request.data)

            EscrowProcessor.process_c2b_payment(txn)

        except Exception as exc:
            FailedMpesaTransaction.objects.create(
                trans_id=txn["trans_id"],
                amount=txn["amount"],
                sender_phone=txn["sender_phone"],
                bill_ref=txn["bill_ref"],
                raw_payload=txn["raw"],
                error=str(exc),
            )

            logger.exception("C2B processing failed", extra={"txn": txn})

            # ALWAYS accept MPESA
            return Response({
                "ResultCode": 0,
                "ResultDesc": "Accepted"
            })
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

