# Standard library
import random
from decimal import Decimal

# Django imports
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.db import transaction

# DRF imports
from rest_framework import generics, permissions, status

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

# Local app imports
from .models import (
    Wallet, PaymentTransaction, EscrowAllocation, WalletLedger,
    Testimonial, UserPin, WithdrawalAudit, MpesaCallbackLog
)
from .serializers import (
    WalletSerializer, WalletCreateSerializer, PaymentTransactionSerializer,
    TestimonialSerializer, CustomerFeedbackSerializer, EscrowAllocationSerializer
)
from .services.walet_balance import get_withdrawable_balance
from wallet.services.fees import calculate_withdrawal_fees

# Utilities
from account.utils import format_kenyan_phone_number
from payments.b2c import trigger_mpesa_b2c


# Create your views here.
def wallet(request):
    context ={}
    return render(request, 'wallet.html', context)




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


class WalletPaymentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet_id = request.GET.get("wallet_id")

        if not wallet_id:
            return Response({"detail": "wallet_id required"}, status=400)

        qs = PaymentTransaction.objects.filter(wallet_id=wallet_id)

        serializer = PaymentTransactionSerializer(qs, many=True)
        return Response({"transactions": serializer.data})
    

def get_wallet_for_user(wallet_id_value, user):
    """
    Accept either wallet PK (UUID/int) or wallet.identifier (string).
    Ensure the wallet belongs to user or user is staff.
    Returns Wallet instance or raises Http404/PermissionDenied externally.
    """
    # Try primary key first
    wallet = None
    try:
        wallet = Wallet.objects.get(pk=wallet_id_value)
    except Exception:
        # fallback to identifier
        wallet = Wallet.objects.filter(identifier=wallet_id_value).first()

    if wallet is None:
        return None

    # permission: either owner or staff
    if getattr(user, 'is_staff', False) or getattr(wallet, 'owner', None) == user:
        return wallet
    return None


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



class ApprovedTestimonialListView(generics.ListAPIView):
    queryset = Testimonial.objects.filter(is_approved=True).order_by("-date_created")
    serializer_class = TestimonialSerializer
    permission_classes = [permissions.AllowAny]


class AddTestimonialView(generics.CreateAPIView):
    serializer_class = TestimonialSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class AddCustomerFeedbackView(generics.CreateAPIView):
    serializer_class = CustomerFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SetPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        raw_pin = request.data.get("pin")

        if not raw_pin or len(raw_pin) < 4:
            return Response({"detail": "PIN must be at least 4 digits."}, status=status.HTTP_400_BAD_REQUEST)

        # Get or create UserPin record
        user_pin, created = UserPin.objects.get_or_create(user=user)

        # Set the PIN but mark it as inactive until OTP verified
        user_pin.set_pin(raw_pin)
        user_pin.is_active = False
        user_pin.generate_otp()  # Generate OTP for verification
        user_pin.save()

        # Return OTP info (in production, you'd send it via SMS/Email instead)
        return Response({
            "detail": "PIN set successfully. Please verify OTP to activate.",
            "otp": user_pin.otp_code,  # for testing only; remove in production
            "otp_expires_in": user_pin.OTP_EXPIRY_SECONDS
        }, status=status.HTTP_201_CREATED)


class VerifyPinOTPView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        otp_input = request.data.get("otp")

        try:
            user_pin = user.pin
        except UserPin.DoesNotExist:
            return Response({"detail": "PIN not set yet."}, status=status.HTTP_400_BAD_REQUEST)

        if user_pin.otp_is_valid(otp_input):
            user_pin.is_active = True
            user_pin.otp_code = None  # clear OTP
            user_pin.otp_created_at = None
            user_pin.save()
            return Response({"detail": "PIN verified and activated successfully."}, status=status.HTTP_200_OK)
        else:
            return Response({"detail": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)


class ResendPinOTPView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        try:
            user_pin = user.pin
        except UserPin.DoesNotExist:
            return Response({"detail": "PIN not set yet."}, status=status.HTTP_400_BAD_REQUEST)

        otp = user_pin.resend_otp()
        return Response({
            "detail": "OTP resent successfully.",
            "otp_expires_in": user_pin.OTP_EXPIRY_SECONDS
        }, status=status.HTTP_200_OK)

class VerifyPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pin = request.data.get("pin")
        user_pin = UserPin.objects.filter(user=request.user).first()  # fetch even if inactive

        # No PIN set at all
        if not user_pin:
            return Response({"detail": "PIN not set"}, status=400)

        # PIN exists but locked
        if user_pin.is_locked():
            return Response({"detail": "PIN locked. Try again later."}, status=status.HTTP_423_LOCKED)

        # If frontend is only checking existence, skip actual pin validation
        if pin == "__check_only__":
            # If OTP verification pending
            if not user_pin.is_active:
                return Response({"detail": "PIN not verified"}, status=200)
            return Response({"detail": "PIN exists"}, status=200)

        # Real PIN validation
        if not user_pin.check_pin(pin):
            WithdrawalAudit.objects.create(
                user=request.user,
                action="PIN_FAILED",
                ip_address=request.META.get("REMOTE_ADDR")
            )
            return Response({"detail": "Invalid PIN"}, status=400)

        return Response({"detail": "PIN verified"}, status=200)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def withdrawal_preview(request):
    user = request.user
    wallet_id = request.data.get("wallet_id")
    amount = request.data.get("amount")

    if not wallet_id or not amount:
        return Response({"detail": "Missing fields"}, status=400)

    try:
        amount = Decimal(amount)
        if amount <= 0:
            raise ValueError
    except Exception:
        return Response({"detail": "Invalid amount"}, status=400)

    try:
        wallet = Wallet.objects.get(id=wallet_id, owner=user)
    except Wallet.DoesNotExist:
        return Response({"detail": "Wallet not found"}, status=404)

    withdrawable = get_withdrawable_balance(wallet)
    fees = calculate_withdrawal_fees(amount, provider="MPESA")
    total =amount + fees["total_fee"]

    if total > withdrawable:
        return Response({
            "detail": "Insufficient balance",
            "withdrawable": str(withdrawable)
        }, status=400)

    return Response({
        "amount": str(amount),
        "fee": str(fees),
        "phone": wallet.owner.username,
        "wallet_id": wallet.id,
        "pin_required": not hasattr(user, "pin"),
    })

def audit(user, action, request, metadata=None):
    WithdrawalAudit.objects.create(
        user=user,
        action=action,
        ip_address=request.META.get("REMOTE_ADDR"),
        metadata=metadata or {}
    )

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def withdrawal_confirm(request):
    user = request.user
    wallet_id = request.data.get("wallet_id")
    amount = request.data.get("amount")
    pin = request.data.get("pin")

    if not pin:
        return Response({"detail": "PIN required"}, status=400)

    if not hasattr(user, "pin") or not user.pin.check_pin(pin):
        audit(user, "PIN_FAILED", request)
        return Response(
            {"detail": "Invalid PIN. If you forgot your PIN, call customer support to reset."},
            status=422
        )

    amount = Decimal(amount).quantize(Decimal("0.01"))

    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().get(
            id=wallet_id,
            owner=user
        )

        fees = calculate_withdrawal_fees(amount, provider="MPESA")
        total = (amount + fees).quantize(Decimal("0.01"))

        withdrawable =  get_withdrawable_balance(wallet)
        if total > withdrawable:
            return Response({"detail": "Insufficient balance"}, status=400)

        # ---- WALLET UPDATE ----
        balance_before = wallet.available_balance
        wallet.available_balance -= total
        wallet.save(update_fields=["available_balance", "updated_at"])

        # ---- PAYMENT RECORD ----
        payment = PaymentTransaction.objects.create(
            transaction_type="WITHDRAWAL",
            wallet=wallet,
            amount=amount,
            transaction_fees=fees,
            external_provider="MPESA",
            sender_phone=wallet.identifier,
            status="PENDING",
            metadata={
                "amount": str(amount),
                "fee": str(fees),
                "total_debited": str(total)
            }
        )

        # ---- LEDGER ENTRY (DEBIT) ----
        WalletLedger.objects.create(
            wallet=wallet,
            entry_type="WITHDRAWAL",
            amount=-total,  # 🔥 debit
            balance_before=balance_before,
            balance_after=wallet.available_balance,
            related_payment=payment,
            meta={"channel": "MPESA_B2C"}
        )

        audit(user, "WITHDRAW", request, {
            "amount": str(amount),
            "fee": str(fees),
            "payment_id": str(payment.id)
        })

    # trigger_mpesa_b2c(payment)

    return Response({
        "status": "PROCESSING",
        "payment_id": str(payment.id)
    })


class MpesaB2CResultCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        result = request.data.get("Result", {})

        conversation_id = result.get("ConversationID")
        result_code = result.get("ResultCode")

        try:
            payment = PaymentTransaction.objects.select_for_update().get(
                checkout_request_id=conversation_id,
                transaction_type="WITHDRAWAL"
            )
        except PaymentTransaction.DoesNotExist:
            MpesaCallbackLog.objects.create(
                conversation_id=conversation_id,
                payload=result
            )

            return Response({"ResultCode": 0, "ResultDesc": "Ignored"})

        # 🔐 Idempotency guard
        if payment.status in ("SUCCESS", "FAILED"):
            return Response({"ResultCode": 0, "ResultDesc": "Already processed"})

        with transaction.atomic():
            if result_code == 0:
                payment.status = "SUCCESS"
                payment.trans_id = result.get("TransactionID")

            else:
                payment.status = "FAILED"
                payment.transaction_fees = 0
                wallet = payment.wallet
                refund_amount = Decimal(payment.metadata["total_debited"])

                balance_before = wallet.available_balance
                wallet.available_balance += refund_amount
                wallet.save(update_fields=["available_balance", "updated_at"])

                # ---- LEDGER ENTRY (CREDIT) ----
                WalletLedger.objects.create(
                    wallet=wallet,
                    entry_type="ADJUSTMENT",
                    amount=refund_amount,  # credit
                    balance_before=balance_before,
                    balance_after=wallet.available_balance,
                    related_payment=payment,
                    meta={"reason": "MPESA B2C failed refund"}
                )

            payment.raw_payload = result
            payment.processed_at = timezone.now()
            payment.save(
                update_fields=[
                    "status",
                    "transaction_fees",
                    "trans_id",
                    "raw_payload",
                    "processed_at"
                ]
            )

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})

from decimal import Decimal
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from wallet.models import Wallet, WalletLedger, PaymentTransaction, EscrowAllocation
from payments.lipanampesa import lipa_na_mpesa
from rest_framework.decorators import api_view, permission_classes
from wallet.escrow_processor import EscrowProcessor

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def initiate_stk_push(request):
    user = request.user
    wallet_id = request.data.get("wallet_id")
    amount = request.data.get("amount")
    receiver_phone = format_kenyan_phone_number(request.data.get("receiver"))
    description = request.data.get("description", "")

    if not wallet_id or not amount or not receiver_phone:
        return Response({"detail": "wallet_id, amount, and receiver required"}, status=400)

    try:
        amount = Decimal(amount).quantize(Decimal("0.01"))
    except:
        return Response({"detail": "Invalid amount"}, status=400)

    with transaction.atomic():
        try:
            wallet = (
                Wallet.objects
                .select_for_update()
                .get(id=wallet_id, owner=user)
            )
        except Wallet.DoesNotExist:
            return Response({"detail": "Wallet not found"}, status=404)

        # --- Create pending payment transaction ---
        payment = PaymentTransaction.objects.create(
            transaction_type="STK_PUSH",
            wallet=wallet,
            amount=amount,
            status="PENDING",
            sender_phone=wallet.identifier,
            account_number=receiver_phone,
            metadata={
                "receiver": receiver_phone,
                "description": description,
            }
        )

        # --- Trigger STK Push ---
        try:
            response = lipa_na_mpesa(
                amount=amount,
                phone_number=receiver_phone,
                account_reference=f"Wallet:{wallet.id}",
                transaction_desc=description,
                callback_url=request.build_absolute_uri("/stk_push/callback/").strip()
            )

            checkout_request_id = response.get("CheckoutRequestID")
            payment.checkout_request_id = checkout_request_id
            payment.save(update_fields=["checkout_request_id"])

        except Exception as e:
            # Any exception rolls back automatically
            raise

    return Response({
        "status": "PENDING",
        "payment_id": payment.id,
        "checkout_request_id": payment.checkout_request_id
    })

class STKPushCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        stk = request.data.get("Body", {}).get("stkCallback")
        if not stk:
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
                transaction_type="STK_PUSH"
            )
        except PaymentTransaction.DoesNotExist:
            MpesaCallbackLog.objects.create(
                conversation_id=merchant_request_id,
                payload=stk
            )
            return Response({"ResultCode": 0, "ResultDesc": "Ignored"})

        if payment.status in ("SUCCESS", "FAILED"):
            return Response({"ResultCode": 0, "ResultDesc": "Already processed"})

        if result_code != 0:
            payment.status = "FAILED"
            payment.raw_payload = stk
            payment.merchant_request_id = merchant_request_id
            payment.processed_at = timezone.now()
            payment.save(update_fields=["status", "raw_payload", "processed_at"])
            return Response({"ResultCode": 0, "ResultDesc": "Failed"})

        txn = {
            "checkout_request_id": checkout_request_id,
            "sender_phone": payment.sender_phone,
            "amount": payment.amount,  # trust your DB, validate against metadata
            "bill_ref": payment.account_number,
            "account_type": payment.metadata.get("account_type", "DIRECT"),
            "raw": stk,
        }

        

        try:
            with transaction.atomic():
                EscrowProcessor.process_lipa_na_mpesa_payment(txn)

                payment.status = "SUCCESS"
                payment.merchant_request_id = merchant_request_id
                payment.processed_at = timezone.now()
                payment.raw_payload = stk
                payment.save(update_fields=["status", "processed_at", "raw_payload"])
        except Exception as e:
            MpesaCallbackLog.objects.create(
                conversation_id=merchant_request_id,
                payload=stk,
                error=str(e)
            )
            return Response({"ResultCode": 1, "ResultDesc": "Processing error"})

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stk_push_status(request):
    """
    Return the current status of a STK Push transaction.
    Frontend polls this endpoint until SUCCESS or FAILED.
    """
    checkout_request_id = request.GET.get("checkout_request_id")
    if not checkout_request_id:
        return Response({"detail": "transaction_id is required"}, status=400)

    try:
        payment = PaymentTransaction.objects.get(checkout_request_id=checkout_request_id, transaction_type="STK_PUSH")
    except PaymentTransaction.DoesNotExist:
        return Response({"status": "UNKNOWN", "reason": "Transaction not found"}, status=404)

    # Map backend status to frontend
    status_map = {
        "PENDING": "PENDING",
        "SUCCESS": "SUCCESS",
        "FAILED": "FAILED",
    }
    status = status_map.get(payment.status, "UNKNOWN")
    reason = getattr(payment, "failure_reason", None)  # optional field if you store failure reasons

    return Response({"status": status, "reason": reason})
