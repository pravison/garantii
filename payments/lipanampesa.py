
import requests
from requests.auth import HTTPBasicAuth

from .access_token import generate_access_token
from .encode import generate_password
from .utils import get_timestamp

from django.conf import settings

def lipa_na_mpesa(payment, callback_url):

    formatted_time = get_timestamp()
    decoded_password = generate_password(formatted_time)
    access_token = generate_access_token()

    # api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    api_url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    headers = {"Authorization": f"Bearer {access_token}"}

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": decoded_password,
        "Timestamp": formatted_time,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(payment.amount),

        # Customer phone
        "PartyA": payment.sender_phone,
        "PhoneNumber": payment.sender_phone,

        # Paybill / Till
        "PartyB": settings.MPESA_SHORTCODE,

        # Callback
        "CallBackURL": callback_url,

        # Account reference shown to customer
        "AccountReference": payment.account_number,

        # Description
        "TransactionDesc": payment.metadata.get("description", "Wallet Deposit"),
    }


    response = requests.post(api_url, json=payload, headers=headers)

    
    try:
        return response.json()
    except ValueError:
        # In case the response isn't JSON
        return {"error": "Invalid response from M-Pesa", "response_text": response.text}

