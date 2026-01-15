from django.utils import timezone
from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models import *
from ..serializers import *
from wallet.escrow_processor import EscrowProcessor
import logging

logger = logging.getLogger(__name__)

class STKPushCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        stk = request.data.get("Body", {}).get("stkCallback")
        if not stk:
            # Optional: log unknown callbacks for monitoring
            log, created = MpesaCallbackLog.objects.update_or_create(
                conversation_id=merchant_request_id,
                defaults={
                    "payload": stk,
                    "error": "Missing stkCallback in payload"
                }
            )
            # Invalid payload, ignore permanently
            return Response({"ResultCode": 0, "ResultDesc": "Invalid payload"})

        checkout_request_id = stk.get("CheckoutRequestID")
        result_code = stk.get("ResultCode")
        merchant_request_id = stk.get("MerchantRequestID")

        # Parse metadata
        metadata = {}
        for item in stk.get("CallbackMetadata", {}).get("Item", []):
            metadata[item["Name"]] = item.get("Value")

        try:
            payment = PaymentTransaction.objects.select_for_update().get(
                checkout_request_id=checkout_request_id,
                transaction_type="DEPOSIT"
            )
        except PaymentTransaction.DoesNotExist:
            # Optional: log unexisting paymenttransaction for monitoring
            log, created = MpesaCallbackLog.objects.update_or_create(
                conversation_id=merchant_request_id,
                defaults={
                    "payload": stk,
                    "error": "payment transaction does not exists"
                }
            )
            # Unknown payment, ignore permanently
            return Response({"ResultCode": 0, "ResultDesc": "Unknown payment, ignored"})

        # Idempotency: already processed
        if payment.status in ("SUCCESS", "FAILED"):
            return Response({"ResultCode": 0, "ResultDesc": "Already processed"})

        # M-Pesa reported failure
        if result_code != 0:
            payment.status = "FAILED"
            payment.raw_payload = stk
            payment.merchant_request_id = merchant_request_id
            payment.processed_at = timezone.now()
            payment.save(update_fields=["status", "raw_payload", "processed_at", "merchant_request_id"])
            
            # Only log transactions that failed to process safely
            log, created = MpesaCallbackLog.objects.update_or_create(
                conversation_id=merchant_request_id,
                defaults={
                    "payload": stk,
                    "error": "transaction failed to be proccesed by mpesa"
                }
            )

            return Response({"ResultCode": 0, "ResultDesc": "Failed transaction, recorded"})

        # Construct txn dict for escrow processing
        txn = {
            "checkout_request_id": checkout_request_id,
            "sender_phone": payment.sender_phone,
            "amount": payment.amount,  # trust DB over metadata
            "bill_ref": payment.account_number,
            "account_type": payment.metadata.get("account_type", "DIRECT"),
            "raw": stk,
        }

        try:
            with transaction.atomic():
                EscrowProcessor.process_lipa_na_mpesa_payment(txn)

                # Mark payment as SUCCESS
                payment.status = "SUCCESS"
                payment.merchant_request_id = merchant_request_id
                payment.processed_at = timezone.now()
                payment.raw_payload = stk
                payment.save(update_fields=["status", "processed_at", "raw_payload", "merchant_request_id"])

        except Exception as e:
            # Only log failed DB / processing errors
            log, created = MpesaCallbackLog.objects.update_or_create(
                conversation_id=merchant_request_id,
                defaults={
                    "payload": stk,
                    "error":"transaction failed to be saved in our database"
                }
            )
            # Tell M-Pesa to retry
            return Response({"ResultCode": 1, "ResultDesc": "Processing error, retry later"})

        # Success, no log needed
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

