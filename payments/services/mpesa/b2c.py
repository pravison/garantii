import json
import time
import requests

from base import MpesaBaseService
from config import (
    MPESA_SHORTCODE,
    MPESA_INITIATOR_NAME,
    MPESA_INITIATOR_SECURITY_CREDENTIAL,
)


class B2CService(MpesaBaseService):
    def __init__(self, sandbox=False):
        super().__init__(sandbox)
        self.shortcode = MPESA_SHORTCODE
        self.initiator = MPESA_INITIATOR_NAME
        self.security_credential = MPESA_INITIATOR_SECURITY_CREDENTIAL

    def withdraw(self, phone_number, amount, remarks="Withdrawal", occasion="Payout"):
        payload = {
            "InitiatorName": self.initiator,
            "SecurityCredential": self.security_credential,
            "CommandID": "BusinessPayment",
            "Amount": int(amount),
            "PartyA": self.shortcode,
            "PartyB": phone_number,
            "Remarks": remarks,
            "QueueTimeOutURL": "https://example.com/b2c-timeout",
            "ResultURL": "https://example.com/b2c-result",
            "Occasion": occasion,
        }

        url = f"{self.base_url}/mpesa/b2c/v1/paymentrequest"
        response = requests.post(url, headers=self.auth_headers(), json=payload)
        data = response.json()

        print("\nB2C INIT RESPONSE")
        print(json.dumps(data, indent=2))

        return data

    def poll(self, conversation_id, interval=10, timeout=120):
        start = time.time()

        while time.time() - start < timeout:
            payload = {
                "Initiator": self.initiator,
                "SecurityCredential": self.security_credential,
                "CommandID": "TransactionStatusQuery",
                "TransactionID": conversation_id,
                "PartyA": self.shortcode,
                "IdentifierType": "4",
                "ResultURL": "https://example.com/result",
                "QueueTimeOutURL": "https://example.com/timeout",
                "Remarks": "B2C verification",
                "Occasion": "B2C",
            }

            url = f"{self.base_url}/mpesa/transactionstatus/v1/query"
            response = requests.post(url, headers=self.auth_headers(), json=payload)
            data = response.json()

            print("\nB2C POLLING RESPONSE")
            print(json.dumps(data, indent=2))

            if data.get("ResponseCode") == "0" and "Result" in data:
                print("\nB2C TRANSACTION COMPLETED")
                return data

            print("\nWAITING FOR B2C PROCESSING...")
            time.sleep(interval)

        print("\nB2C POLLING TIMED OUT")
        return None
