import base64
import datetime
import json
import time
import requests

from base import MpesaBaseService
from config import MPESA_SHORTCODE, MPESA_PASSKEY


class StkPushService(MpesaBaseService):
    def __init__(self, sandbox=False):
        super().__init__(sandbox)
        self.shortcode = MPESA_SHORTCODE
        self.passkey = MPESA_PASSKEY

    def initiate(self, phone_number, amount, account_reference="Payment"):
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            f"{self.shortcode}{self.passkey}{timestamp}".encode()
        ).decode()

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(amount),
            "PartyA": phone_number,
            "PartyB": self.shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": "https://example.com/callback",
            "AccountReference": account_reference,
            "TransactionDesc": "STK Push Payment",
        }

        url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"
        response = requests.post(url, headers=self.auth_headers(), json=payload)
        data = response.json()

        print("\nSTK PUSH RESPONSE")
        print(json.dumps(data, indent=2))

        return data

    def poll(self, checkout_request_id, interval=5, timeout=60):
        start = time.time()

        while time.time() - start < timeout:
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            password = base64.b64encode(
                f"{self.shortcode}{self.passkey}{timestamp}".encode()
            ).decode()

            payload = {
                "BusinessShortCode": self.shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id,
            }

            url = f"{self.base_url}/mpesa/stkpushquery/v1/query"
            response = requests.post(url, headers=self.auth_headers(), json=payload)
            data = response.json()

            print("\nSTK POLLING RESPONSE")
            print(json.dumps(data, indent=2))

            code = data.get("ResultCode")
            if code == "0":
                print("\nSTK PAYMENT SUCCESSFUL")
                return data

            if code in ["1032", "1037", "2001"]:
                print("\nSTK PAYMENT FAILED OR CANCELLED")
                return data

            print("\nWAITING FOR CUSTOMER ACTION...")
            time.sleep(interval)

        print("\nSTK POLLING TIMED OUT")
        return None
