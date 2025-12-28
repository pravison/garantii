import requests
from requests.auth import HTTPBasicAuth

from .access_token import generate_access_token
from .encode import generate_password
from .utils import get_timestamp

from django.conf import settings


def lipa_na_mpesa(amount, phone_number, account_reference, transaction_desc, callback_url):
    """
    Initiates an STK Push (Lipa na M-Pesa) transaction.
    
    Parameters:
        amount (str|int): The amount to charge the customer.
        phone_number (str): The customer's phone number in format 2547XXXXXXXX.
        account_reference (str): Account reference for tracking, e.g., Wallet ID.
        transaction_desc (str): Description of the transaction.
        callback_url (str): URL for receiving payment confirmation.
        
    Returns:
        dict: Response from M-Pesa API.
    """
    formatted_time = get_timestamp()
    decoded_password = generate_password(formatted_time)
    access_token = generate_access_token()

    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {"Authorization": f"Bearer {access_token}"}

    

    payload = {
        "Password": "MTc0Mzc5YmZiMjc5ZjlhYTliZGJjZjE1OGU5N2RkNzFhNDY3Y2QyZTBjODkzMDU5YjEwZjc4ZTZiNzJhZGExZWQyYzkxOTIwMjUxMjI4MDkwODM0",
        "BusinessShortCode": "174379",
        "Timestamp": "20251228090834",
        "Amount": "1",
        "PartyA": "254706420043",
        "PartyB": "174379",
        "TransactionType": "CustomerPayBillOnline",
        "PhoneNumber": "254706420043",
        "TransactionDesc": "Test",
        "AccountReference": "Test",
        "CallBackURL": callback_url
        }

    response = requests.post(api_url, json=payload, headers=headers)
    
    try:
        return response.json()
    except ValueError:
        # In case the response isn't JSON
        return {"error": "Invalid response from M-Pesa", "response_text": response.text}

