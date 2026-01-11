# import requests
# from requests.auth import HTTPBasicAuth
# from django.conf import settings


# def generate_access_token():

#     consumer_key = settings.MPESA_CONSUMER_KEY
#     consumer_secret = settings.MPESA_CONSUMER_SECRET
#     # api_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
#     api_URL = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

#     try:
#         r = requests.get(api_URL, auth=HTTPBasicAuth(consumer_key, consumer_secret))
#     except:
#         r = requests.get(api_URL, auth=HTTPBasicAuth(consumer_key, consumer_secret), verify=False)
        
#     print(r.text)

#     json_response = (
#         r.json()
#     )  # {'access_token': 'orfE9Dun2qqCpuXsORjcWGzvrAIY', 'expires_in': '3599'}

#     my_access_token = json_response["access_token"]

#     return my_access_token


import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings


def generate_access_token():
    api_URL = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"

    consumer_key = settings.MPESA_CONSUMER_KEY
    consumer_secret = settings.MPESA_CONSUMER_SECRET

    r = requests.get(
        api_URL,
        auth=HTTPBasicAuth(consumer_key, consumer_secret),
        timeout=10,
    )

    # 🔴 HARD FAIL WITH REAL MESSAGE
    if r.status_code != 200:
        raise Exception(
            f"M-Pesa OAuth failed | "
            f"Status: {r.status_code} | "
            f"Response: {r.text}"
        )

    try:
        data = r.json()
    except ValueError:
        raise Exception(f"M-Pesa OAuth returned non-JSON response: {r.text}")

    return data["access_token"]
