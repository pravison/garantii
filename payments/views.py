from django.shortcuts import render


from rest_framework.views import APIView
from rest_framework.response import Response
# Create your views here.
# mpesa/views/c2b_validation.py

from wallet.models import Wallet
from payments.utils import identify_account_number
from payments.get_customer_order import get_order_allocations

# mpesa validation url 
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



from payments.services.mpesa_parser import MpesaC2BParser
from wallet.escrow_processor import EscrowProcessor


class MpesaC2BConfirmationView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            txn = MpesaC2BParser.parse_confirmation(request.data)
            EscrowProcessor.process_c2b_payment(txn)
        except Exception:
            return Response({"ResultCode": 1, "ResultDesc": "Failed"})

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

