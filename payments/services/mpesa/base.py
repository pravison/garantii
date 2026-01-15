import requests
from config import (
    MPESA_CONSUMER_KEY,
    MPESA_CONSUMER_SECRET,
)

class MpesaBaseService:
    def __init__(self, sandbox=False):
        self.consumer_key = MPESA_CONSUMER_KEY
        self.consumer_secret = MPESA_CONSUMER_SECRET

        self.base_url = (
            "https://sandbox.safaricom.co.ke"
            if sandbox
            else "https://api.safaricom.co.ke"
        )

        self.access_token = self.get_access_token()

    def get_access_token(self):
        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        response = requests.get(url, auth=(self.consumer_key, self.consumer_secret))
        response.raise_for_status()
        return response.json()["access_token"]

    def auth_headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
