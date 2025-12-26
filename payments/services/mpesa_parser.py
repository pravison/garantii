# mpesa/services/mpesa_parser.py

from decimal import Decimal

from payments.utils import normalize_msisdn, identify_account_number


class MpesaC2BParser:

    @staticmethod
    def parse_confirmation(data: dict) -> dict:
        return {
            "trans_id": data["TransID"],
            "amount": Decimal(data["TransAmount"]),
            "bill_ref": data["BillRefNumber"],
            "sender_phone": normalize_msisdn(data["MSISDN"]),
            "account_type": identify_account_number(data["BillRefNumber"]),
            "raw": data,
        }
