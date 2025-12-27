# mpesa/domain/escrow_processor.py

from django.db import transaction
from django.utils import timezone

from wallet.models import Wallet, WalletLedger, PaymentTransaction, EscrowAllocation
from payments.get_customer_order import get_order_allocations


class EscrowProcessor:

    @staticmethod
    @transaction.atomic
    def process_c2b_payment(txn: dict):

        if PaymentTransaction.objects.filter(trans_id=txn["trans_id"]).exists():
            return

        buyer_wallet, _ = Wallet.objects.select_for_update().get_or_create(
            identifier=txn["sender_phone"],
            defaults={"meta": {"auto_created": True}},
        )

        # Get or create PaymentTransaction
        payment, created = PaymentTransaction.objects.update_or_create(
            trans_id=txn["trans_id"],  # unique identifier for the transaction
            defaults={
                "transaction_type": "DEPOSIT",
                "status": "SUCCESS",
                "wallet_id": buyer_wallet.id,
                "amount": txn["amount"],
                "sender_phone": txn["sender_phone"],
                "account_number": txn["bill_ref"],
                "external_provider": "MPESA",
                "received_at": timezone.now(),
                "processed_at": timezone.now(),
                "raw_payload": txn["raw"],
            }
        )


        # Credit buyer
        before = buyer_wallet.available_balance
        buyer_wallet.available_balance += txn["amount"]
        buyer_wallet.save(update_fields=["available_balance", "updated_at"])

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="DEPOSIT",
            amount=txn["amount"],
            balance_before=before,
            balance_after=buyer_wallet.available_balance,
            related_payment=payment,
        )

        # Lock buyer funds
        buyer_wallet.available_balance -= txn["amount"]
        buyer_wallet.send_locked_balance += txn["amount"]
        buyer_wallet.save(update_fields=["available_balance", "send_locked_balance", "updated_at"])

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="ESCROW_HOLD",
            amount=-txn["amount"],
            balance_before=before + txn["amount"],
            balance_after=buyer_wallet.available_balance,
            related_payment=payment,
        )

        # Allocation
        allocations = []

        if txn["account_type"] == "ORDER":
            items = get_order_allocations(txn["bill_ref"])
            for item in items:
                seller_wallet = Wallet.objects.select_for_update().get(
                    identifier=item["seller_identifier"]
                )
                allocations.append((seller_wallet, item["amount"], item["description"]))

        else:
            seller_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                identifier=txn["bill_ref"],
                defaults={"meta": {"auto_created": True}},
            )
            allocations.append((seller_wallet, txn["amount"], "Direct escrow payment"))

        total = sum(a[1] for a in allocations)
        if total != txn["amount"]:
            raise ValueError("Allocation mismatch")

        for seller_wallet, amount, desc in allocations:
            EscrowAllocation.objects.create(
                payment=payment,
                payer_wallet=buyer_wallet,
                receiver_wallet=seller_wallet,
                receiver_phone=seller_wallet.identifier,
                amount=amount,
                description=desc,
                status="HELD",
            )

            seller_wallet.receive_locked_balance += amount
            seller_wallet.save(update_fields=["receive_locked_balance", "updated_at"])

        payment.reconciled = True
        payment.save(update_fields=["reconciled"])
