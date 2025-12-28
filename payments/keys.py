

from django.conf import settings

# Lipa Na Mpesa credentials
business_shortCode = settings.MPESA_SHORTCODE
shortcode = settings.MPESA_SHORTCODE
lipa_na_mpesa_passkey = settings.MPESA_PASSKEY

# OAuth credentials
consumer_key = settings.MPESA_CONSUMER_KEY
consumer_secret = settings.MPESA_CONSUMER_SECRET

# Optional / dynamic values
phone_number = None      # set per transaction
test_msisdn = None       # only if testing
