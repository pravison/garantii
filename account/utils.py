
import re
import phonenumbers

def format_kenyan_phone_number(phone_raw: str) -> str:
    """
    Format Kenyan phone numbers to E.164 (without '+').
    Accepts: +2547XXXXXXXX, 07XXXXXXXX, 7XXXXXXXX, 2547XXXXXXXX, 0110XXXXXX, etc.
    Returns: E.164 format as string (e.g., 254712345678)
    """
    if not phone_raw:
        raise ValueError("Phone number is required.")

    # Strip spaces, dashes, parentheses
    phone_cleaned = re.sub(r'[^\d+]', '', phone_raw.strip())

    # Normalize leading digits
    if phone_cleaned.startswith("00"):
        phone_cleaned = "+" + phone_cleaned[2:]
    elif phone_cleaned.startswith("+"):
        pass  # already international format
    elif phone_cleaned.startswith("0"):
        # Leading zero → could be mobile or landline
        phone_cleaned = "+254" + phone_cleaned[1:]
    elif phone_cleaned.startswith("254"):
        phone_cleaned = "+" + phone_cleaned
    elif phone_cleaned.startswith("1") or phone_cleaned.startswith("11") or phone_cleaned.startswith("10"):
        # landline missing leading 0, e.g., 110778912 → add +254
        phone_cleaned = "+254" + phone_cleaned
    elif phone_cleaned.startswith("7") and len(phone_cleaned) == 9:
        # mobile without leading zero
        phone_cleaned = "+254" + phone_cleaned
    else:
        raise ValueError("Unrecognized phone number format.")

    try:
        parsed_number = phonenumbers.parse(phone_cleaned, "KE")
        if not phonenumbers.is_valid_number(parsed_number):
            raise ValueError("Invalid Kenyan phone number.")

        # Return E.164 format without '+'
        return phonenumbers.format_number(
            parsed_number, phonenumbers.PhoneNumberFormat.E164
        ).replace('+', '')

    except phonenumbers.NumberParseException:
        raise ValueError("Error parsing phone number.")

