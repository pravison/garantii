# serializers.py
from rest_framework import serializers
from .models import Wallet, PaymentTransaction
from .models import EscrowAllocation, CustomerFeedback

from .models import Testimonial

from django.contrib.auth import get_user_model

User = get_user_model()


class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "trans_id",
            "transaction_type",
            "status",
            "amount",
            "sender_phone",
            "account_number",
            "external_provider",
            "received_at",
            "processed_at",
            "raw_payload",
            "reconciled",
            "metadata",
            "created_at",
        ]


class WalletSerializer(serializers.ModelSerializer):
    total_locked = serializers.SerializerMethodField()
    withdrawable_balance = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = [
            'id',
            'identifier',
            'available_balance',
            'send_locked_balance',
            'receive_locked_balance',
            'total_locked',
            'withdrawable_balance',
            'created_at'
        ]

    def get_total_locked(self, obj):
        return obj.send_locked_balance + obj.receive_locked_balance

    def get_withdrawable_balance(self, obj):
        total_locked = obj.send_locked_balance + obj.receive_locked_balance
        return obj.available_balance - total_locked


class WalletCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ['id', 'identifier', 'is_business']


class EscrowAllocationSerializer(serializers.ModelSerializer):
    payer_wallet_identifier = serializers.CharField(source='payer_wallet.identifier', read_only=True)
    receiver_wallet_identifier = serializers.CharField(source='receiver_wallet.identifier', read_only=True)
    # include payer/receiver ids (db primary keys) if needed by frontend
    payer_wallet_id = serializers.PrimaryKeyRelatedField(source='payer_wallet', read_only=True)
    receiver_wallet_id = serializers.PrimaryKeyRelatedField(source='receiver_wallet', read_only=True)

    class Meta:
        model = EscrowAllocation
        fields = [
            'id',
            'order_id',
            'description',
            'payer_wallet_identifier',
            'receiver_wallet_identifier',
            'payer_wallet_id',
            'receiver_wallet_id',
            'receiver_phone',
            'amount',
            'commission',
            'status',
            'created_at',
            'released_at',
            'extra'
        ]
        read_only_fields = fields


class TestimonialSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Testimonial
        fields = ["id", "user_name", "message", "image", "date_created"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    
class CustomerFeedbackSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomerFeedback
        fields = ["id", "user_name", "feedback_type", "message", "image", "date_created"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
