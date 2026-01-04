# payments/mpesa/b2c.py
import uuid
import requests
from django.conf import settings

from payments.access_token import generate_access_token

def trigger_mpesa_b2c(payment):
    """
    Sends money to customer via Mpesa B2C
    """
    token = generate_access_token()

    payload = {
        "InitiatorName": settings.MPESA_INITIATOR_NAME,
        "SecurityCredential": settings.MPESA_SECURITY_CREDENTIAL,
        "CommandID": "BusinessPayment",
        "Amount": int(payment.amount),
        "PartyA": settings.MPESA_SHORTCODE,
        "PartyB": payment.sender_phone,  # customer phone
        "Remarks": "Wallet Withdrawal",
        "QueueTimeOutURL": settings.MPESA_B2C_TIMEOUT_URL,
        "ResultURL": settings.MPESA_B2C_RESULT_URL,
        "Occasion": str(payment.id)
    }

    res = requests.post(
        settings.MPESA_B2C_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=30
    )

    res.raise_for_status()
    data = res.json()

    payment.checkout_request_id = data.get("ConversationID")
    payment.merchant_request_id = data.get("OriginatorConversationID")
    payment.save(update_fields=["checkout_request_id", "merchant_request_id"])

    return data

