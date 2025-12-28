# mpesa/domain/escrow_processor.py

from django.db import transaction
from django.utils import timezone

from wallet.models import Wallet, WalletLedger, PaymentTransaction, EscrowAllocation
from payments.get_customer_order import get_order_allocations



class EscrowProcessor:

    # =========================
    # C2B PROCESSOR
    # =========================
    @staticmethod
    @transaction.atomic
    def process_c2b_payment(txn: dict):
        """
        C2B payments:
        - Unique key: trans_id (MpesaReceiptNumber)
        """

        # Idempotency (C2B retries happen)
        payment, created = PaymentTransaction.objects.get_or_create(
            trans_id=txn["trans_id"],
            defaults={
                "transaction_type": "DEPOSIT",
                "status": "SUCCESS",
                "amount": txn["amount"],
                "sender_phone": txn["sender_phone"],
                "account_number": txn["bill_ref"],
                "external_provider": "MPESA",
                "received_at": timezone.now(),
                "processed_at": timezone.now(),
                "raw_payload": txn["raw"],
            }
        )

        if not created and payment.reconciled:
            return

        # Lock buyer wallet row
        buyer_wallet, _ = Wallet.objects.select_for_update().get_or_create(
            identifier=txn["sender_phone"],
            defaults={"meta": {"auto_created": True}},
        )

        payment.wallet = buyer_wallet
        payment.save(update_fields=["wallet"])

        # ===== Ledger: Deposit =====
        before = buyer_wallet.available_balance

        buyer_wallet.available_balance += txn["amount"]
        buyer_wallet.send_locked_balance += txn["amount"]
        buyer_wallet.save(update_fields=[
            "available_balance",
            "send_locked_balance",
            "updated_at"
        ])

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="DEPOSIT",
            amount=txn["amount"],
            balance_before=before,
            balance_after=before + txn["amount"],
            related_payment=payment,
        )

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="ESCROW_HOLD",
            amount=-txn["amount"],
            balance_before=before + txn["amount"],
            balance_after=before,
            related_payment=payment,
        )

        # ===== Allocation =====
        allocations = []

        if txn["account_type"] == "ORDER":
            items = get_order_allocations(txn["bill_ref"])
            for item in items:
                seller_wallet = Wallet.objects.select_for_update().get(
                    identifier=item["seller_identifier"]
                )
                allocations.append(
                    (seller_wallet, item["amount"], item["description"])
                )
        else:
            seller_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                identifier=txn["bill_ref"],
                defaults={"meta": {"auto_created": True}},
            )
            allocations.append(
                (seller_wallet, txn["amount"], "Direct escrow payment")
            )

        if sum(a[1] for a in allocations) != txn["amount"]:
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
            seller_wallet.save(update_fields=[
                "receive_locked_balance",
                "updated_at"
            ])

        payment.reconciled = True
        payment.save(update_fields=["reconciled"])

    # =========================
    # STK (LIPA NA MPESA) PROCESSOR
    # =========================
    @staticmethod
    @transaction.atomic
    def process_lipa_na_mpesa_payment(txn: dict):
        """
        STK Push payments:
        - Unique key: checkout_request_id
        - trans_id (MpesaReceiptNumber) arrives AFTER success
        """

        # Idempotency guard (Safaricom retries callbacks)
        existing = PaymentTransaction.objects.filter(
            checkout_request_id=txn["checkout_request_id"],
            reconciled=True
        ).exists()

        if existing:
            return

        buyer_wallet, _ = Wallet.objects.select_for_update().get_or_create(
            identifier=txn["sender_phone"],
            defaults={"meta": {"auto_created": True}},
        )

        payment, _ = PaymentTransaction.objects.update_or_create(
            checkout_request_id=txn["checkout_request_id"],
            defaults={
                "trans_id": txn.get("trans_id"),  # MpesaReceiptNumber
                "transaction_type": "DEPOSIT",
                "status": "SUCCESS",
                "wallet": buyer_wallet,
                "amount": txn["amount"],
                "sender_phone": txn["sender_phone"],
                "account_number": txn["bill_ref"],
                "external_provider": "MPESA",
                "received_at": timezone.now(),
                "processed_at": timezone.now(),
                "raw_payload": txn["raw"],
            }
        )

        # ===== Ledger: Deposit =====
        before = buyer_wallet.available_balance

        buyer_wallet.available_balance += txn["amount"]
        buyer_wallet.send_locked_balance += txn["amount"]
        buyer_wallet.save(update_fields=[
            "available_balance",
            "send_locked_balance",
            "updated_at"
        ])

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="DEPOSIT",
            amount=txn["amount"],
            balance_before=before,
            balance_after=before + txn["amount"],
            related_payment=payment,
        )

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="ESCROW_HOLD",
            amount=-txn["amount"],
            balance_before=before + txn["amount"],
            balance_after=before,
            related_payment=payment,
        )

        # ===== Allocation =====
        allocations = []

        if txn["account_type"] == "ORDER":
            items = get_order_allocations(txn["bill_ref"])
            for item in items:
                seller_wallet = Wallet.objects.select_for_update().get(
                    identifier=item["seller_identifier"]
                )
                allocations.append(
                    (seller_wallet, item["amount"], item["description"])
                )
        else:
            seller_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                identifier=txn["bill_ref"],
                defaults={"meta": {"auto_created": True}},
            )
            allocations.append(
                (seller_wallet, txn["amount"], "Direct escrow payment")
            )

        if sum(a[1] for a in allocations) != txn["amount"]:
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
            seller_wallet.save(update_fields=[
                "receive_locked_balance",
                "updated_at"
            ])

        payment.reconciled = True
        payment.save(update_fields=["reconciled"])

