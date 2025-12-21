from django.shortcuts import render
# escrow/api/views.py

from decimal import Decimal
from django.utils import timezone

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .models import Wallet, PaymentTransaction
from .serializers import WalletSerializer, WalletCreateSerializer,  PaymentTransactionSerializer, TestimonialSerializer, CustomerFeedbackSerializer
import random

from .models import EscrowAllocation, WalletLedger
from .serializers import EscrowAllocationSerializer



from rest_framework import status as http_status
from django.shortcuts import get_object_or_404
from django.db import transaction

from account.utils import format_kenyan_phone_number
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



@api_view(['GET'])
def escrow_transactions(request):
    wallet_id = request.GET.get("wallet_id")

#     if not wallet_id:
#         return Response({"error": "wallet_id is required"}, status=400)

#     sent = EscrowAllocation.objects.filter(payment__sender_phone=wallet_id)
#     received = EscrowAllocation.objects.filter(receiver_phone=wallet_id)

#     # Serialize
#     sent_ser = EscrowAllocationSerializer(sent, many=True).data
#     for t in sent_ser:
#         t["direction"] = "SENT"

#     received_ser = EscrowAllocationSerializer(received, many=True).data
#     for t in received_ser:
#         t["direction"] = "RECEIVED"

#     combined = sent_ser + received_ser

#     return Response({"transactions": combined})


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
            return Response({"detail": "wallet_id required"}, status=http_status.HTTP_400_BAD_REQUEST)

        wallet = get_wallet_for_user(wallet_id, request.user)
        if wallet is None:
            return Response({"detail": "Wallet not found or access denied"}, status=http_status.HTTP_404_NOT_FOUND)

        qs = EscrowAllocation.objects.filter(payer_wallet=wallet) | EscrowAllocation.objects.filter(receiver_wallet=wallet)
        qs = qs.order_by('-created_at')

        serializer = EscrowAllocationSerializer(qs, many=True)
        return Response({"transactions": serializer.data}, status=http_status.HTTP_200_OK)


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
            return Response({"detail": "Not allowed to reverse this escrow or invalid status"}, status=http_status.HTTP_403_FORBIDDEN)

        try:
            with transaction.atomic():
                updated = escrow.request_reversal(user=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=http_status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": "Failed to request reversal"}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = EscrowAllocationSerializer(updated)
        return Response({"detail": "Reversal requested successfully", "transaction": serializer.data}, status=http_status.HTTP_200_OK)


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
            return Response({"detail": "extra info required"}, status=http_status.HTTP_400_BAD_REQUEST)

        escrow = get_object_or_404(EscrowAllocation, id=escrow_id)

        if not escrow.can_add_extra_by(request.user):
            return Response({"detail": "Not allowed to add info (already exists or not owner)"}, status=http_status.HTTP_403_FORBIDDEN)

        try:
            with transaction.atomic():
                updated = escrow.add_extra(extra_info, user=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=http_status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({"detail": "Failed to save extra info"}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = EscrowAllocationSerializer(updated)
        return Response({"detail": "Extra information added successfully", "transaction": serializer.data}, status=http_status.HTTP_200_OK)

from rest_framework import generics, permissions
from .models import Testimonial

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


import re
import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response

PHONE_REGEX = re.compile(r"(?:254|0)(?:7|1)\d{8}")

def normalize_msisdn(msisdn: str) -> str:
    msisdn = msisdn.strip()
    if msisdn.startswith("0"):
        return "254" + msisdn[1:]
    return msisdn


def identify_account_number(value: str) -> str:
    if not value:
        return "UNKNOWN"

    value = value.strip()

    if PHONE_REGEX.fullmatch(value):
        return "PHONE"

    if value.isdigit() and len(value) == 6:
        return "BUSINESS_TILL"

    if value.upper().startswith("ORD"):
        return "ORDER"

    return "UNKNOWN"

class OrderAllocationError(Exception):
    pass


def get_order_allocations(order_id):
    try:
        resp = requests.get(
            f"{settings.ECOMMERCE_BASE_URL}/api/orders/{order_id}/escrow-allocations/",
            headers={
                "Authorization": f"Bearer {settings.ECOMMERCE_SERVICE_TOKEN}",
            },
            timeout=10,
        )
    except requests.RequestException:
        raise OrderAllocationError("Ecommerce unreachable")

    if resp.status_code != 200:
        raise OrderAllocationError("Order not found")

    data = resp.json()
    items = data.get("items")

    if not isinstance(items, list) or not items:
        raise OrderAllocationError("Invalid order data")

    allocations = []

    for item in items:
        try:
            amount = Decimal(item["amount"])
        except (KeyError, InvalidOperation):
            raise OrderAllocationError("Invalid amount")

        allocations.append({
            "order_id": order_id,
            "seller_identifier": item["seller_identifier"],
            "amount": amount,
            "description": item.get("description", ""),
        })

    return allocations


class MpesaC2BConfirmationView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = request.data

        # -------- Parse --------
        trans_id = data.get("TransID")
        bill_ref = data.get("BillRefNumber")
        sender_phone = data.get("MSISDN")

        try:
            amount = Decimal(data.get("TransAmount"))
        except (InvalidOperation, TypeError):
            return Response({"ResultCode": 1, "ResultDesc": "Invalid amount"})

        if not all([trans_id, bill_ref, sender_phone]):
            return Response({"ResultCode": 1, "ResultDesc": "Invalid payload"})

        sender_phone = normalize_msisdn(sender_phone)
        acct_type = identify_account_number(bill_ref)

        # -------- PRE-VALIDATION (NO DB WRITES) --------
        try:
            if acct_type == "BUSINESS_TILL":
                Wallet.objects.get(identifier=bill_ref, is_business=True)

            elif acct_type == "ORDER":
                get_order_allocations(bill_ref)

            elif acct_type == "PHONE":
                pass  # always acceptable

            else:
                return Response({"ResultCode": 1, "ResultDesc": "Invalid account"})

        except Exception:
            return Response({"ResultCode": 1, "ResultDesc": "Invalid reference"})

        # -------- IDEMPOTENCY --------
        if PaymentTransaction.objects.filter(trans_id=trans_id).exists():
            return Response({"ResultCode": 0, "ResultDesc": "Already processed"})

        # -------- ACCEPT PAYMENT --------
        with transaction.atomic():

            # Buyer wallet (auto-create)
            buyer_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                identifier=sender_phone,
                defaults={
                    "is_business": False,
                    "meta": {"auto_created": True},
                },
            )

            payment = PaymentTransaction.objects.create(
                trans_id=trans_id,
                transaction_type="DEPOSIT",
                status="SUCCESS",
                wallet=buyer_wallet,
                amount=amount,
                sender_phone=sender_phone,
                account_number=bill_ref,
                external_provider="MPESA",
                received_at=timezone.now(),
                processed_at=timezone.now(),
                raw_payload=data,
            )

            # Credit buyer
            before = buyer_wallet.available_balance
            buyer_wallet.available_balance += amount
            buyer_wallet.save(update_fields=["available_balance", "updated_at"])

            WalletLedger.objects.create(
                wallet=buyer_wallet,
                entry_type="DEPOSIT",
                amount=amount,
                balance_before=before,
                balance_after=buyer_wallet.available_balance,
                related_payment=payment,
            )

            # Lock buyer funds
            buyer_wallet.available_balance -= amount
            buyer_wallet.send_locked_balance += amount
            buyer_wallet.save(update_fields=[
                "available_balance",
                "send_locked_balance",
                "updated_at",
            ])

            WalletLedger.objects.create(
                wallet=buyer_wallet,
                entry_type="ESCROW_HOLD",
                amount=-amount,
                balance_before=before + amount,
                balance_after=buyer_wallet.available_balance,
                related_payment=payment,
            )

            # -------- ALLOCATION --------
            try:
                allocations = []

                if acct_type == "ORDER":
                    order_items = get_order_allocations(bill_ref)
                    for item in order_items:
                        seller_wallet = Wallet.objects.select_for_update().get(
                            identifier=item["seller_identifier"]
                        )
                        allocations.append({
                            "order_id": bill_ref,
                            "seller_wallet": seller_wallet,
                            "amount": item["amount"],
                            "description": item["description"],
                        })

                else:
                    seller_wallet = Wallet.objects.select_for_update().get_or_create(
                        identifier=bill_ref,
                        defaults={"meta": {"auto_created": True}},
                    )[0]

                    allocations.append({
                        "order_id": None,
                        "seller_wallet": seller_wallet,
                        "amount": amount,
                        "description": "Direct escrow payment",
                    })

                total = sum(a["amount"] for a in allocations)
                if total != amount:
                    raise ValueError("Allocation mismatch")

                for alloc in allocations:
                    EscrowAllocation.objects.create(
                        payment=payment,
                        order_id=alloc["order_id"],
                        description=alloc["description"],
                        payer_wallet=buyer_wallet,
                        receiver_wallet=alloc["seller_wallet"],
                        receiver_phone=alloc["seller_wallet"].identifier,
                        amount=alloc["amount"],
                        status="HELD",
                    )

                    alloc["seller_wallet"].receive_locked_balance += alloc["amount"]
                    alloc["seller_wallet"].save(update_fields=[
                        "receive_locked_balance",
                        "updated_at",
                    ])

                payment.reconciled = True
                payment.save(update_fields=["reconciled"])

            except Exception:
                payment.status = "PENDING"
                payment.metadata["allocation_failed"] = True
                payment.save(update_fields=["status", "metadata"])

        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})
