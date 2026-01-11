# payments/mpesa/b2c.py
from django_daraja.mpesa.core import MpesaClient


def trigger_mpesa_b2c(payment):
    """
    Sends money to customer via Mpesa B2C
    """
    cl = MpesaClient()
    phone_number = payment.sender_phone
    amount = int(payment.amount)
    transaction_desc = 'Wallet Withdrawal'
    occassion = 'Occassion'
    callback_url = 'https://garantiipay.vercel.app/withdrawals/confirm/'
    cl.business_payment(phone_number, amount, transaction_desc, callback_url, occassion)

