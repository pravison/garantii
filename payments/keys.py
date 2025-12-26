from decouple import config, Csv

business_shortCode = config("BUSINESS_SHORTCODE")  # Lipa Na Mpesa Shortcode
phone_number = config("PHONE_NUMBER")
lipa_na_mpesa_passkey = config("LNM_PASSKEY")
consumer_key = config("CONSUMER_KEY")
consumer_secret = config("CONSUMER_SECRET")
shortcode = config("SHORTCODE")
test_msisdn = config("TEST_MSISDN")


from django.conf import settings

# Lipa Na Mpesa credentials
business_shortCode = settings.DARJA_SHORTCODE
shortcode = settings.DARJA_SHORTCODE
lipa_na_mpesa_passkey = settings.DARJA_PASSKEY

# OAuth credentials
consumer_key = settings.DARJA_CONSUMER_KEY
consumer_secret = settings.DARJA_CONSUMER_SECRET

# Optional / dynamic values
phone_number = None      # set per transaction
test_msisdn = None       # only if testing
