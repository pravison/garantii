# Standard library
import random
from decimal import Decimal
import json
from django.core.exceptions import ValidationError

from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import PermissionDenied
# Django imports
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

from wallet.models import EscrowAllocation
from payments.lipanampesa import lipa_na_mpesa
from wallet.escrow_processor import EscrowProcessor

import logging

logger = logging.getLogger(__name__)


from django.db.models import Sum


from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render

from django.db.models import Case, When, IntegerField
from datetime import timedelta

@staff_member_required
@permission_required('payments.view_escrowallocation', raise_exception=True)
def escrowProductFlow(request):
    """
    Staff view to list escrow allocations.
    Can filter by:
      - product flow stage (?flow_stage=...)
      - date: today or yesterday (?date_filter=today/yesterday)
    Can sort by:
      - product flow (?sort=product_flow)
      - newest first (?sort=date_new)
      - oldest first (?sort=date_old)
    """

    escrows = EscrowAllocation.objects.select_related(
        'payer_wallet', 'receiver_wallet', 'payment'
    )

    # --- Filters ---
    flow_stage = request.GET.get('flow_stage')
    if flow_stage:
        escrows = escrows.filter(product_flow_status=flow_stage)

    date_filter = request.GET.get('date_filter')
    if date_filter == 'today':
        escrows = escrows.filter(created_at__date=timezone.now().date())
    elif date_filter == 'yesterday':
        escrows = escrows.filter(created_at__date=timezone.now().date() - timedelta(days=1))

    # --- Sorting ---
    sort = request.GET.get('sort', 'date_new')
    if sort == 'product_flow':
        flow_order = {
            'CUSTOMER_PAYED': 1,
            'SENT_TO_COURIER': 2,
            'RECEIVED_BY_COURIER': 3,
            'DELIVERED_BY_COURIER': 4,
            'CUSTOMER_RECEIVED': 5,
        }
        whens = [When(product_flow_status=k, then=v) for k, v in flow_order.items()]
        escrows = escrows.annotate(flow_order=Case(*whens, output_field=IntegerField()))
        escrows = escrows.order_by('flow_order', '-created_at')
    elif sort == 'date_old':
        escrows = escrows.order_by('created_at')
    else:  # date_new or default
        escrows = escrows.order_by('-created_at')

    context = {
        "escrows": escrows,
        "flow_stage": flow_stage,
        "date_filter": date_filter,
        "sort": sort,
        "product_flow_choices": EscrowAllocation.PRODUCT_FLOW_STATUS,
        "now": timezone.now(),
    }

    return render(request, 'escrow_product_flow.html', context)

# function for updating receivers available balance
# onec customer has confirmed to reeive the product

def accept_customer_received(*, escrow, staff_user, reason):
    """
    Confirm customer received product:
    - Release escrow funds to seller
    - Deduct locked balances
    - Create ledger entries
    - Update escrow status + product flow
    - Add audit trail
    """

    # business rules
    if escrow.status == 'REVERSE_REQUESTED':
        raise ValidationError("Escrow has a pending reversal request resolve the reversal request fast before continuing.")

    if escrow.status != 'HELD':
        raise ValidationError("Only HELD escrows can be released")

    if escrow.status == "RELEASED":
        raise ValidationError("Escrow already marked as RELEASED.")

    with transaction.atomic():
        # Lock wallets
        payer_wallet = Wallet.objects.select_for_update().get(pk=escrow.payer_wallet_id)
        receiver_wallet = Wallet.objects.select_for_update().get(pk=escrow.receiver_wallet_id)

        if not payer_wallet or not receiver_wallet:
            raise ValidationError("Missing wallets on escrow.")

        # Safety checks
        if payer_wallet.send_locked_balance < escrow.amount:
            raise ValidationError("Insufficient sender locked balance")

        if receiver_wallet.receive_locked_balance < escrow.amount:
            raise ValidationError("Insufficient receiver locked balance")

        # ---- Move balances ----

        # Deduct locked balances
        payer_wallet.send_locked_balance -= escrow.amount
        payer_wallet.save(update_fields=["send_locked_balance"])

        receiver_wallet.receive_locked_balance -= escrow.amount

        receiver_before = receiver_wallet.available_balance
        receiver_wallet.available_balance += escrow.amount
        receiver_wallet.save(update_fields=[
            "receive_locked_balance",
            "available_balance"
        ])

        # ---- Ledger entry for receiver (seller) ----
        WalletLedger.objects.create(
            wallet=receiver_wallet,
            entry_type="ESCROW_RELEASE",
            amount=escrow.amount,
            balance_before=receiver_before,
            balance_after=receiver_wallet.available_balance,
            related_allocation=escrow,
            meta={
                "staff_id": staff_user.id,
                "staff": staff_user.username,
                "reason": reason,
            },
        )

        # ---- Update escrow ----
        escrow.status = "RELEASED"
        escrow.product_flow_status = "CUSTOMER_RECEIVED"
        escrow.released_at = timezone.now()

        escrow.extra = escrow.extra or {}
        escrow.extra.setdefault("product_flow_updates", []).append({
            "action": "customer_received",
            "staff_id": staff_user.id,
            "staff_name": staff_user.get_username(),
            "reason": reason,
            "at": timezone.now().isoformat(),
        })

        escrow.save(update_fields=[
            "status",
            "product_flow_status",
            "released_at",
            "extra"
        ])

        return escrow


@staff_member_required
@require_POST
def update_product_flow(request):
    """
    Staff updates the product flow stage for an escrow.
    Adds metadata with staff id, name, stage, and reason.
    """
    escrow_id = request.POST.get('escrow_id')
    new_stage = request.POST.get('new_stage')
    reason = request.POST.get('reason', '').strip()
    staff_user = request.user
    if not new_stage or not reason:
        messages.success(request, "Stage and reason are required.")
        return redirect(request.META.get('HTTP_REFERER', '/'))
    try:
        with transaction.atomic():
            escrow = EscrowAllocation.objects.select_for_update().get(id=escrow_id)
            old_stage = escrow.product_flow_status
            if new_stage == 'CUSTOMER_RECEIVED':
                accept_customer_received(
                    escrow=escrow,
                    staff_user=request.user,
                    reason=reason,
                )
            else:
                escrow.product_flow_status = new_stage
                escrow.extra = escrow.extra or {}
                escrow.extra.setdefault('update_product_flow', []).append({
                    'staff_id': staff_user.id,
                    'staff_name': staff_user.get_full_name() or staff_user.username,
                    'from_stage': old_stage,
                    'to_stage': new_stage,
                    'reason': reason,
                    'ts': timezone.now().isoformat()
                })
                escrow.save()
    except ValidationError as e:
        messages.error(request, e.message)
        return redirect(request.META.get('HTTP_REFERER', '/'))

    messages.success(
        request,
        f"Product flow updated from {old_stage} → {new_stage}."
    )
    return redirect(request.META.get('HTTP_REFERER', '/'))

    

@staff_member_required
@permission_required('payments.view_escrowallocation', raise_exception=True)
def escrowReversalRequests(request):
    """
    Staff-only view to list escrow transactions
    that have a reversal request.
    """
    # if not request.user.is_authenticated:
    #     return redirect("wallet")
    # if not request.user.is_staff:
    #     return redirect("wallet")
    # if not request.user.has_permision.view():
    #     return redirect("wallet")
    
    escrows = (
        EscrowAllocation.objects
        .select_related(
            'payer_wallet',
            'receiver_wallet',
            'payment'
        )
        .filter(status='REVERSE_REQUESTED')
        .order_by('-created_at')
    )

    totals = escrows.aggregate(
        total_amount=Sum('amount'),
        total_commission=Sum('commission')
    )

    context = {
        "escrows": escrows,
        "totals": totals,
        "page_title": "Escrow Reversal Requests",
        "now": timezone.now(),
        "status": "REVERSE_REQUESTED",
    }

    return render(request, 'escrow_reversal_requests.html', context)


def accept_escrow_reversal(*, escrow, staff_user, reason):
    """
    Accept escrow reversal:
    - Return funds to payer
    - Deduct locked funds from receiver
    - Create ledger entries
    - Update escrow + audit trail
    """
    if escrow.status != 'REVERSE_REQUESTED':
        raise ValidationError("Escrow is not in REVERSE_REQUESTED state")

    with transaction.atomic():
        # Lock wallets
        payer_wallet = Wallet.objects.select_for_update().get(pk=escrow.payer_wallet_id)
        receiver_wallet = Wallet.objects.select_for_update().get(pk=escrow.receiver_wallet_id)

        if not payer_wallet or not receiver_wallet:
            raise ValidationError("Missing wallets on escrow")

        # Safety checks
        if payer_wallet.send_locked_balance < escrow.amount:
            raise ValidationError("Invalid sender locked balance")

        if receiver_wallet.receive_locked_balance < escrow.amount:
            raise ValidationError("Invalid receiver locked balance")

        # Reverse escrow balances
        receiver_wallet.receive_locked_balance -= escrow.amount
        receiver_wallet.save(update_fields=["receive_locked_balance"])

        payer_before = payer_wallet.available_balance
        payer_wallet.send_locked_balance -= escrow.amount
        payer_wallet.available_balance += escrow.amount
        payer_wallet.save(update_fields=["send_locked_balance", "available_balance"])

        # Create ledger for payer
        WalletLedger.objects.create(
            wallet=payer_wallet,
            entry_type="ESCROW_REFUND",
            amount=escrow.amount,
            balance_before=payer_before,
            balance_after=payer_wallet.available_balance,
            related_allocation=escrow,
            meta={
                "staff_id": staff_user.id,
                "staff": staff_user.username,
                "reason": reason,
            },
        )

        # Update escrow
        escrow.status = "REVERSED"
        escrow.released_at = timezone.now()
        escrow.extra = escrow.extra or {}
        escrow.extra["reversal_decision"] = {
            "staff_id": staff_user.id,
            "staff_name": staff_user.get_username(),
            "action": "ACCEPTED",
            "reason": reason,
            "at": timezone.now().isoformat(),
        }
        escrow.save(update_fields=["status", "released_at", "extra"])
       

@require_POST
def escrow_reversal_action(request):
    user = request.user

    if not (user.is_authenticated and user.is_staff):
        raise PermissionDenied

    if not user.has_perm('payments.change_escrowallocation'):
        raise PermissionDenied

    data = json.loads(request.body)
    escrow_id = data.get('escrow_id')
    action = data.get('action')
    reason = data.get('reason')

    if action not in ['ACCEPT', 'DENY'] or not reason:
        return JsonResponse({"message": "Invalid request"}, status=400)
    try:
        with transaction.atomic():
            escrow = EscrowAllocation.objects.select_for_update().get(
                id=escrow_id,
                status='REVERSE_REQUESTED'
            )

            # ---- Audit trail ----
            escrow.extra = escrow.extra or {}
            escrow.extra['reversal_decision'] = {
                "staff_id": user.id,
                "staff_name": user.get_full_name() or user.username,
                "action": action,
                "reason": reason,
                "at": timezone.now().isoformat(),
            }

            if action == 'DENY':
                escrow.status = 'HELD'
                escrow.save()

                return JsonResponse({
                    "message": "Reversal denied and escrow restored to HELD."
                })

            # ---- ACCEPT REVERSAL ----
            accept_escrow_reversal(
                escrow=escrow,
                staff_user=user,
                reason=reason,
            )


        return JsonResponse({
            "message": "Reversal accepted, funds returned, ledger updated."
        })
    except ValidationError as e:
        return JsonResponse(
            {"message": e.messages},
            status=400
        )

    

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
    fees_amount = fees["total_fee"]
    total = (amount + fees_amount).quantize(Decimal("0.01"))
    
    if total > withdrawable:
        return Response({
            "detail": "Insufficient balance",
            "withdrawable": str(withdrawable)
        }, status=400)

    return Response({
        "amount": str(amount),
        "fee": str(fees),
        "phone": wallet.owner.username if wallet.is_business else wallet.identifier,
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
    try:
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

        # Convert amount safely
        try:
            amount = Decimal(amount).quantize(Decimal("0.01"))
        except Exception:
            return Response({"detail": "Invalid amount"}, status=400)

        with transaction.atomic():
            try:
                wallet = Wallet.objects.select_for_update().get(
                    id=wallet_id,
                    owner=user
                )
            except Wallet.DoesNotExist:
                return Response({"detail": "Wallet not found"}, status=404)

            fees = calculate_withdrawal_fees(amount, provider="MPESA")
            fees_amount = fees["total_fee"]
            total = (amount + fees_amount).quantize(Decimal("0.01"))

            withdrawable = get_withdrawable_balance(wallet)
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
                sender_phone=wallet.owner.username if wallet.is_business else wallet.identifier,
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

            # Audit the withdrawal
            audit(user, "WITHDRAW", request, {
                "amount": str(amount),
                "fee": str(fees),
                "payment_id": str(payment.id)
            })

        # ---- TRIGGER MPESA B2C ----
        try:
            trigger_mpesa_b2c(payment)

        except Exception as e:
            # If B2C fails, roll back wallet and ledger
            logger.error(f"MPESA B2C trigger failed for payment {payment.id}: {str(e)}")

            with transaction.atomic():
                # Refund wallet
                wallet = payment.wallet
                wallet.available_balance += Decimal(payment.metadata["total_debited"])
                wallet.save(update_fields=["available_balance", "updated_at"])

                # Create ledger adjustment entry
                WalletLedger.objects.create(
                    wallet=wallet,
                    entry_type="ADJUSTMENT",
                    amount=Decimal(payment.metadata["total_debited"]),  # credit back
                    balance_before=balance_before - total,  # original before debit
                    balance_after=wallet.available_balance,
                    related_payment=payment,
                    meta={"reason": "MPESA B2C failed refund"}
                )

                # Update payment status
                payment.status = "FAILED"
                payment.save(update_fields=["status"])

            return Response({
                "status": "FAILED",
                "detail": "Withdrawal failed. Please try again after a few minutes."
            }, status=500)

        # If everything is ok
        return Response({
            "status": "PROCESSING",
            "payment_id": str(payment.id)
        })

    except Exception as exc:
        logger.exception(f"Withdrawal failed for user {request.user.id}: {str(exc)}")
        return Response({"detail": "An error occurred while processing your withdrawal."}, status=500)

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
            transaction_type="DEPOSiT",
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
        payment = PaymentTransaction.objects.get(checkout_request_id=checkout_request_id)
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
