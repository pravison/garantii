# mpesa/domain/escrow_processor.py

from django.db import transaction
from django.utils import timezone

from wallet.models import Wallet, WalletLedger, PaymentTransaction, EscrowAllocation
from payments.get_customer_order import get_order_allocations

from payments.utils import identify_account_number


class EscrowProcessor:

    # =========================
    # C2B PROCESSOR
    # =========================
    @staticmethod
    @transaction.atomic
    def process_c2b_payment(txn: dict):
        """
        Process MPESA C2B payment.
        Idempotent by MpesaReceiptNumber (trans_id).
        """

        # ===== 1. Idempotency =====
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

        # ===== 2. Lock buyer wallet =====
        buyer_wallet, _ = Wallet.objects.select_for_update().get_or_create(
            identifier=txn["sender_phone"],
            defaults={"meta": {"auto_created": True}},
        )

        payment.wallet = buyer_wallet
        payment.save(update_fields=["wallet"])

        # ===== 3. Lock funds (deposit → escrow hold) =====
        before_balance = buyer_wallet.available_balance

        buyer_wallet.send_locked_balance += txn["amount"]
        buyer_wallet.save(update_fields=["send_locked_balance", "updated_at"])

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="DEPOSIT",
            amount=txn["amount"],
            balance_before=before_balance,
            balance_after=before_balance + txn["amount"],
            related_payment=payment,
        )

        WalletLedger.objects.create(
            wallet=buyer_wallet,
            entry_type="ESCROW_HOLD",
            amount=-txn["amount"],
            balance_before=before_balance + txn["amount"],
            balance_after=before_balance,
            related_payment=payment,
        )

        # ===== 4. Build allocations (NO DB WRITES YET) =====
        allocations = []
        acct_type = identify_account_number(txn["bill_ref"])

        try:
            if acct_type == "BUSINESS_TILL":
                seller_wallet, _ = Wallet.objects.select_for_update().get(
                    identifier=txn["bill_ref"],
                    is_business=True,
                    defaults={"meta": {"auto_created": True}},
                )
                allocations.append((seller_wallet, txn["amount"], "Direct till payment"))

            elif acct_type == "PHONE":
                seller_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                    identifier=txn["bill_ref"],
                    defaults={"meta": {"auto_created": True}},
                )
                allocations.append((seller_wallet, txn["amount"], "Direct phone payment"))

            elif acct_type == "ORDER":
                items = get_order_allocations(txn["bill_ref"])

                for item in items:
                    seller_wallet = Wallet.objects.select_for_update().get(
                        identifier=item["seller_identifier"]
                    )
                    allocations.append(
                        (seller_wallet, item["amount"], item["description"])
                    )

            else:
                raise ValueError("Unsupported account number")

        except Exception as exc:
            # ===== 5. Reversal (automatic via transaction.atomic) =====
            raise ValueError(f"Allocation failed: {exc}")

        # ===== 6. Validate allocation total =====
        total_allocated = sum(a[1] for a in allocations)
        if total_allocated != txn["amount"]:
            raise ValueError("Allocation amount mismatch")

        # ===== 7. Create escrow allocations =====
        for seller_wallet, amount, description in allocations:
            EscrowAllocation.objects.create(
                payment=payment,
                payer_wallet=buyer_wallet,
                receiver_wallet=seller_wallet,
                receiver_phone=seller_wallet.identifier,
                amount=amount,
                description=description,
                status="HELD",
            )

            seller_wallet.receive_locked_balance += amount
            seller_wallet.save(update_fields=["receive_locked_balance", "updated_at"])

        # ===== 8. Mark reconciled =====
        payment.reconciled = True
        payment.save(update_fields=["reconciled"])

        
    # =========================
    # STK (LIPA NA MPESA) PROCESSOR
    # =========================
    
    @staticmethod
    @transaction.atomic
    def process_lipa_na_mpesa_payment(txn: dict):
        """
        Process an STK Push payment safely.
        txn keys:
            - checkout_request_id
            - sender_phone
            - amount
            - bill_ref
            - raw
            - trans_id (MpesaReceiptNumber, optional)
        """

        checkout_request_id = txn["checkout_request_id"]
        amount = txn["amount"]
        sender_phone = txn["sender_phone"]
        bill_ref = txn["bill_ref"]

        # --- 1. Idempotency guard ---
        existing = PaymentTransaction.objects.filter(
            checkout_request_id=checkout_request_id,
            reconciled=True
        ).exists()
        if existing:
            return  # Already processed, ignore

        # --- 2. Buyer wallet ---
        buyer_wallet, _ = Wallet.objects.select_for_update().get_or_create(
            identifier=sender_phone,
            defaults={"meta": {"auto_created": True}},
        )

        # --- 3. Payment transaction record ---
        payment, _ = PaymentTransaction.objects.update_or_create(
            checkout_request_id=checkout_request_id,
            defaults={
                "trans_id": txn.get("trans_id"),
                "transaction_type": "DEPOSIT",
                "status": "SUCCESS",
                "wallet": buyer_wallet,
                "amount": amount,
                "sender_phone": sender_phone,
                "account_number": bill_ref,
                "external_provider": "MPESA",
                "received_at": timezone.now(),
                "processed_at": timezone.now(),
                "raw_payload": txn["raw"],
            }
        )

        # --- 4. Ledger: deposit + escrow hold ---
        before_balance = buyer_wallet.available_balance
        buyer_wallet.send_locked_balance += amount
        buyer_wallet.save(update_fields=["send_locked_balance", "updated_at"])

        WalletLedger.objects.bulk_create([
            WalletLedger(
                wallet=buyer_wallet,
                entry_type="DEPOSIT",
                amount=amount,
                balance_before=before_balance,
                balance_after=before_balance + amount,
                related_payment=payment
            ),
            WalletLedger(
                wallet=buyer_wallet,
                entry_type="ESCROW_HOLD",
                amount=-amount,
                balance_before=before_balance + amount,
                balance_after=before_balance,
                related_payment=payment
            )
        ])

        # --- 5. Allocation ---
        allocations = []
        acct_type = identify_account_number(bill_ref)
        customer_description = payment.metadata.get("description", "")
        try:
            if acct_type == "BUSINESS_TILL":
                seller_wallet = Wallet.objects.select_for_update().get(
                    identifier=bill_ref,
                    is_business=True
                )
                allocations.append((seller_wallet, amount, customer_description))

            elif acct_type == "PHONE":
                seller_wallet, _ = Wallet.objects.select_for_update().get_or_create(
                    identifier=bill_ref,
                    defaults={"meta": {"auto_created": True}},
                )
                allocations.append((seller_wallet, amount, customer_description))

            elif acct_type == "ORDER":
                items = get_order_allocations(bill_ref)
                for item in items:
                    seller_wallet = Wallet.objects.select_for_update().get(
                        identifier=item["seller_identifier"]
                    )
                    allocations.append(
                        (seller_wallet, item["amount"], item["description"])
                    )

            else:
                raise ValueError(f"Unsupported account number type: {bill_ref}")

        except Exception as exc:
            # Automatic rollback via transaction.atomic
            raise ValueError(f"Allocation preparation failed: {exc}")

        # --- 6. Validate allocations ---
        total_allocated = sum(a[1] for a in allocations)
        if total_allocated != amount:
            raise ValueError(f"Allocation total mismatch: txn={amount}, allocated={total_allocated}")

        # --- 7. Perform allocations ---
        for seller_wallet, alloc_amount, desc in allocations:
            EscrowAllocation.objects.create(
                payment=payment,
                payer_wallet=buyer_wallet,
                receiver_wallet=seller_wallet,
                receiver_phone=seller_wallet.identifier,
                amount=alloc_amount,
                description=desc,
                status="HELD"
            )
            seller_wallet.receive_locked_balance += alloc_amount
            seller_wallet.save(update_fields=["receive_locked_balance", "updated_at"])

        # --- 8. Mark payment reconciled ---
        payment.reconciled = True
        payment.save(update_fields=["reconciled"])
