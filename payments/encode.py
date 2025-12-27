import base64

from django.conf import settings

def generate_password(formatted_time):

    data_to_encode = (
        settings.MPESA_SHORTCODE + settings.MPESA_PASSKEY + formatted_time
    )

    encoded_string = base64.b64encode(data_to_encode.encode())
    # print(encoded_string) b'MjAxOTAyMjQxOTUwNTc='

    decoded_password = encoded_string.decode("utf-8")

    return decoded_password
