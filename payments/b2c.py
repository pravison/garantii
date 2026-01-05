# payments/mpesa/b2c.py
import uuid
import requests
from django.conf import settings
from django.http import HttpResponse
from payments.access_token import generate_access_token
from django_daraja.mpesa.core import MpesaClient


def trigger_mpesa_b2c(payment):
    """
    Sends money to customer via Mpesa B2C
    """
    # token = generate_access_token()
    # b2c_url=https://sandbox.safaricom.co.ke/mpesa/b2c/v3/paymentrequest

    # payload = {
    #     "InitiatorName": settings.MPESA_INITIATOR_NAME,
    #     "SecurityCredential": settings.MPESA_SECURITY_CREDENTIAL,
    #     "CommandID": "BusinessPayment",
    #     "Amount": int(payment.amount),
    #     "PartyA": settings.MPESA_SHORTCODE,
    #     "PartyB": payment.sender_phone,  # customer phone
    #     "Remarks": "Wallet Withdrawal",
    #     "QueueTimeOutURL": settings.MPESA_B2C_TIMEOUT_URL,
    #     "ResultURL": settings.MPESA_B2C_RESULT_URL,
    #     "Occasion": str(payment.id)
    # }

    # res = requests.post(
    #     b2c_url,
    #     json=payload,
    #     headers={
    #         "Authorization": f"Bearer {token}",
    #         "Content-Type": "application/json"
    #     },
    #     timeout=30
    # )

    # res.raise_for_status()
    # data = res.json()

    # payment.checkout_request_id = data.get("ConversationID")
    # payment.merchant_request_id = data.get("OriginatorConversationID")
    # payment.save(update_fields=["checkout_request_id", "merchant_request_id"])

    # return data
    cl = MpesaClient()
    phone_number = payment.sender_phone
    amount = int(payment.amount)
    transaction_desc = 'Wallet Withdrawal'
    occassion = 'Occassion'
    callback_url = 'https://garantiipay.vercel.app/withdrawals/confirm/'
    response = cl.business_payment(phone_number, amount, transaction_desc, callback_url, occassion)
    return HttpResponse(response)


