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
