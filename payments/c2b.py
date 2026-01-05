import requests
from django.conf import settings
from .access_token import generate_access_token


def register_url():

    my_access_token = generate_access_token()

    api_url = "https://sandbox.safaricom.co.ke/mpesa/c2b/v1/registerurl"

    headers = {"Authorization": "Bearer %s" % my_access_token}

    request = {
        "ShortCode": "4002785",
        "ResponseType": "Completed",
        "ConfirmationURL": "https://garantiipay.vercel.app/payment/api/c2b-confirmation-url/",
        "ValidationURL":   "https://garantiipay.vercel.app/payment/api/c2b-validation-url/",
    }

    try:
        response = requests.post(api_url, json=request, headers=headers)
    except:
        response = requests.post(api_url, json=request, headers=headers, verify=False)

    print(response.text)





# def simulate_c2b_transaction():
#     my_access_token = generate_access_token()

#     api_url = "https://sandbox.safaricom.co.ke/mpesa/c2b/v1/simulate"

#     headers = {"Authorization": "Bearer %s" % my_access_token}

#     request = {
#         "ShortCode": keys.shortcode,
#         "CommandID": "CustomerPayBillOnline",
#         "Amount": "4",
#         "Msisdn": keys.test_msisdn,
#         "BillRefNumber": "myaccnumber",
#     }
#     try:
#         response = requests.post(api_url, json=request, headers=headers)

#     except:
#         response = requests.post(api_url, json=request, headers=headers, verify=False)

#     print(response.text)


# simulate_c2b_transaction()
