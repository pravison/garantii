from decimal import Decimal
import logging
from django.db.models import Sum
from ..models import WalletReconciliationLog

logger = logging.getLogger("finance.reconciliation")


def get_withdrawable_balance(wallet):
    """
    Defensive withdrawable balance calculation.

    Returns the LOWER of:
    - wallet.available_balance (cached balance)
    - ledger-derived balance (source of truth)

    Logs a warning if the two differ.
    """

    # 1️⃣ Wallet-side balance (already withdrawable-only by design)
    wallet_balance = wallet.available_balance or Decimal("0.00")

    # 2️⃣ Ledger-derived balance (sum of all ledger amounts)
    ledger_balance = (
        wallet.ledger_entries.aggregate(
            total=Sum("amount")
        )["total"]
        or Decimal("0.00")
    )

    # Normalize
    wallet_balance = wallet_balance.quantize(Decimal("0.01"))
    ledger_balance = ledger_balance.quantize(Decimal("0.01"))

    # 3️⃣ Detect mismatch
    if wallet_balance != ledger_balance:
        WalletReconciliationLog.objects.create(
            wallet=wallet,
            wallet_balance=wallet_balance,
            ledger_balance=ledger_balance,
            difference=wallet_balance - ledger_balance,
        )


    # 4️⃣ Return safest value
    return max(
        Decimal("0.00"),
        min(wallet_balance, ledger_balance)
    )
