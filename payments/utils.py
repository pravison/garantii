from datetime import datetime

import re

PHONE_REGEX = re.compile(r"(?:254|0)(?:7|1)\d{8}")

def normalize_msisdn(msisdn: str) -> str:
    msisdn = msisdn.strip()
    if msisdn.startswith("0"):
        return "254" + msisdn[1:]
    return msisdn


def identify_account_number(value: str) -> str:
    if not value:
        return "UNKNOWN"

    value = value.strip()

    if PHONE_REGEX.fullmatch(value):
        return "PHONE"

    if value.isdigit() and len(value) == 6:
        return "BUSINESS_TILL"

    if value.upper().startswith("ORD"):
        return "ORDER"

    return "UNKNOWN"


def get_timestamp():
    unformatted_time = datetime.now()
    formatted_time = unformatted_time.strftime("%Y%m%d%H%M%S")

    return formatted_time
