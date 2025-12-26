from decimal import Decimal
from ..models import FeeRule

from django.utils import timezone
from django.db.models import Q

def calculate_withdrawal_fees(amount: Decimal, provider="MPESA"):
    """
    Returns a dict with provider_fee, platform_fee, total_fee
    """
    now = timezone.now()

    rule = FeeRule.objects.filter(
        fee_type="WITHDRAWAL",
        provider=provider,
        min_amount__lte=amount,
        max_amount__gte=amount,
        is_active=True,
        effective_from__lte=now,
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=now)
    ).first()

    if not rule:
        raise ValueError("No withdrawal fee rule configured")

    return {
        "provider_fee": rule.provider_fee,
        "platform_fee": rule.platform_fee,
        "total_fee": rule.total_fee,
    }
