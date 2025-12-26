from django.contrib import admin

# Register your models here.
from .models import Wallet, PaymentTransaction, EscrowAllocation, WalletLedger, Testimonial

admin.site.register(Wallet)
admin.site.register(PaymentTransaction)
admin.site.register(WalletLedger)
admin.site.register(Testimonial)


@admin.register(EscrowAllocation)
class EscrowAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "order_id",
        "payer_wallet",
        "receiver_wallet",
        "amount",
        "status",
        "created_at",
    )

    list_filter = (
        "status",
        "created_at",
        "payer_wallet",
        "receiver_wallet",
    )

    search_fields = (
        "order_id",
        "description",
        "receiver_phone",
        "payer_wallet__id",
        "receiver_wallet__id",
    )

    ordering = ("-created_at",)


from .models import CustomerFeedback


@admin.register(CustomerFeedback)
class CustomerFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "feedback_type",
        "user",
        "is_resolved",
        "date_created",
    )

    list_filter = (
        "feedback_type",
        "is_resolved",
        "date_created",
        "user",
    )

    search_fields = ("message", "user__username", "user__email")

from .models import WithdrawalAudit
admin.site.register(WithdrawalAudit)

from .models import UserPin
admin.site.register(UserPin)

from .models import WalletReconciliationLog
@admin.register(WalletReconciliationLog)
class WalletReconciliationLogAdmin(admin.ModelAdmin):
    list_display = (
        "wallet",
        "wallet_balance",
        "ledger_balance",
        "difference",
        "detected_at",
    )


from .models import FeeRule


@admin.register(FeeRule)
class FeeRuleAdmin(admin.ModelAdmin):
    # Columns shown in list view
    list_display = (
        "fee_type",
        "provider",
        "min_amount",
        "max_amount",
        "provider_fee",
        "platform_fee",
        "total_fee_display",
        "is_active",
        "effective_from",
        "effective_to",
    )

    # Built-in filters (right sidebar)
    list_filter = (
        "fee_type",
        "provider",
        "is_active",
        "effective_from",
    )

    # Built-in search (top search bar)
    search_fields = (
        "fee_type",
        "provider",
    )

    # Default ordering
    ordering = ("fee_type", "provider", "min_amount")

    # Readonly calculated field
    readonly_fields = ("total_fee_display",)

    # Field layout when editing
    fieldsets = (
        ("Fee Identification", {
            "fields": ("fee_type", "provider", "is_active")
        }),
        ("Amount Range", {
            "fields": ("min_amount", "max_amount")
        }),
        ("Fees", {
            "fields": ("provider_fee", "platform_fee", "total_fee_display")
        }),
        ("Validity Period", {
            "fields": ("effective_from", "effective_to")
        }),
    )

    def total_fee_display(self, obj):
        return obj.provider_fee + obj.platform_fee

    total_fee_display.short_description = "Total Fee"

