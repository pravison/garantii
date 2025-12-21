# models.py
import uuid
from decimal import Decimal
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone

User = settings.AUTH_USER_MODEL

class Wallet(models.Model):
    owner = models.ForeignKey(User,null=True, blank=True, on_delete=models.SET_NULL, related_name='wallets')
    is_business = models.BooleanField(default=False)
    identifier = models.CharField(max_length=64, unique=True)  # phone for personal, shortcode for business
    available_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    send_locked_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))    # funds held awaiting release to others
    receive_locked_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00')) # optional other locked bucket
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['identifier']),
            models.Index(fields=['owner']),
        ]

    def __str__(self):
        return f"Wallet {self.identifier} ({self.owner})"

    # convenience operations (use services for production)
    def total_balance(self):
        return self.balance

    def total_locked(self):
        return self.send_locked_balance + self.receive_locked_balance


class PaymentTransaction(models.Model):
    TRANSACTION_TYPES = [
        ("DEPOSIT", "Deposit from external provider (MPESA C2B)"),
        ("WITHDRAWAL", "Withdrawal to external provider (B2C)"),
    ]
    STATUS = [
        ("PENDING", "Pending"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trans_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)  # external provider id (may be null for internal)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=10, choices=STATUS, default="PENDING")

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='payment_transactions', null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    sender_phone = models.CharField(max_length=15, null=True, blank=True)
    account_number = models.CharField(max_length=64, null=True, blank=True)
    external_provider = models.CharField(max_length=32, null=True, blank=True)  # "MPESA", "BANK", etc.
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    reconciled = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    checkout_request_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    merchant_request_id = models.CharField(max_length=64, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['trans_id']),
            models.Index(fields=['transaction_type']),
        ]

    def __str__(self):
        return f"{self.transaction_type} {self.trans_id or self.pk} - {self.amount}"


class WalletLedger(models.Model):
    ENTRY_TYPES = [
        ("DEPOSIT", "External deposit"),
        ("ESCROW_HOLD", "Escrow hold (locked)"),
        ("ESCROW_RELEASE", "Escrow release (to recipient)"),
        ("ESCROW_REFUND", "Refund to buyer (internal)"),
        ("COMMISSION", "Platform commission"),
        ("WITHDRAWAL", "External withdrawal"),
        ("TRANSFER", "Internal transfer between wallets"),
        ("ADJUSTMENT", "Manual adjustment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='ledger_entries')
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)  # +ve or -ve depending on convention (we'll use positive for credit, negative for debit)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    related_payment = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    related_allocation = models.ForeignKey('EscrowAllocation', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'entry_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Ledger {self.entry_type} {self.amount} for {self.wallet.identifier}"


class EscrowAllocation(models.Model):
    ALLOC_STATUS = [
        ('HELD', 'Held'),
        ('RELEASE_REQUESTED', 'Release Requested'),
        ('RELEASED', 'Released'),
        ('REFUNDED', 'Refunded'),
        ('REVERSE_REQUESTED', 'Reverse Requested'),
        ('REVERSED', 'Reversed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey('PaymentTransaction', on_delete=models.PROTECT, related_name='allocations', null=True, blank=True)
    order_id = models.CharField(max_length=64, null=True, blank=True, help_text='id for product purchased')
    description = models.CharField(max_length=255, null=True, blank=True)
    payer_wallet = models.ForeignKey('Wallet', on_delete=models.PROTECT, related_name='escrow_paid_allocations', null=True, blank=True)
    receiver_wallet = models.ForeignKey('Wallet', on_delete=models.PROTECT, related_name='escrow_received_allocations', null=True, blank=True)
    receiver_phone = models.CharField(max_length=15, null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    commission = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=ALLOC_STATUS, default='HELD')
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)  # store reasons, dispute ids, notes

    class Meta:
        indexes = [
            models.Index(fields=['order_id']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Escrow {self.order_id or self.id} {self.amount} {self.status}"

    # utility helpers
    def can_be_reversed_by(self, user):
        """
        Only the payer (owner of payer_wallet) or staff can reverse HELD escrows.
        """
        if self.status != 'HELD':
            return False
        if self.payer_wallet and hasattr(self.payer_wallet, 'owner'):
            return self.payer_wallet.owner == user or getattr(user, 'is_staff', False)
        return False

    def can_add_extra_by(self, user):
        """
        Only the payer (owner of payer_wallet) or staff can add extra if description empty.
        """
        if self.description:
            return False
        if self.payer_wallet and hasattr(self.payer_wallet, 'owner'):
            return self.payer_wallet.owner == user or getattr(user, 'is_staff', False)
        return False

    def add_extra(self, extra_data: str, user=None):
        """
        Atomic add extra (description) and optionally record metadata in JSON field.
        """
        if not extra_data:
            raise ValueError("empty extra_data")
        with transaction.atomic():
            # re-fetch to protect against race
            current = EscrowAllocation.objects.select_for_update().get(pk=self.pk)
            if current.description:
                raise ValueError("description already set")
            current.description = extra_data
            # optional: store who added
            if user is not None:
                current.extra = current.extra or {}
                current.extra.setdefault('history', []).append({
                    'action': 'add_extra',
                    'by': getattr(user, 'id', None),
                    'ts': timezone.now().isoformat()
                })
            current.save()
            return current

    def request_reversal(self, user=None):
        """
        Atomic status change to REVERSED (or raise).
        """
        with transaction.atomic():
            current = EscrowAllocation.objects.select_for_update().get(pk=self.pk)
            if current.status != 'HELD':
                raise ValueError("Only HELD transactions can be reversed")
            current.status = 'REVERSE_REQUESTED'
            current.extra = current.extra or {}
            current.extra.setdefault('history', []).append({
                'action': 'request_reversal',
                'by': getattr(user, 'id', None),
                'ts': timezone.now().isoformat()
            })
            current.save()
            return current


def testimonial_upload_path(instance, filename):
    # uploads to: /testimonials/user_<id>/<filename>
    return f"testimonials/user_{instance.user.id}/{filename}"


class Testimonial(models.Model):
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="testimonials"
    )

    message = models.TextField()

    image = models.ImageField(
        upload_to=testimonial_upload_path,
        blank=True,
        null=True,
        help_text="Upload a screenshot, proof image, etc."
    )

    is_approved = models.BooleanField(
        default=False,
        help_text="Admin approval before showing publicly"
    )

    date_created = models.DateTimeField(auto_now_add=True)

    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Testimonial by {self.user} ({self.id})"

class CustomerFeedback(models.Model):
    FEEDBACK_TYPES = [
        ("FEEDBACK", "General Feedback"),
        ("COMPLAINT", "Complaint / Issue"),
    ]

    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_feedback"
    )

    feedback_type = models.CharField(
        max_length=20,
        choices=FEEDBACK_TYPES,
        default="FEEDBACK"
    )

    message = models.TextField()

    image = models.ImageField(
        upload_to="customer_feedback/",
        null=True,
        blank=True,
        help_text="Optional screenshot or proof image"
    )

    is_resolved = models.BooleanField(default=False)   # for admin tracking
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.feedback_type} by {self.user} ({self.id})"
