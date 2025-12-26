
import re
import requests
from decimal import Decimal, InvalidOperation

from django.conf import settings

class OrderAllocationError(Exception):
    pass


def get_order_allocations(order_id):
    try:
        resp = requests.get(
            f"{settings.ECOMMERCE_BASE_URL}/api/orders/{order_id}/escrow-allocations/",
            headers={
                "Authorization": f"Bearer {settings.ECOMMERCE_SERVICE_TOKEN}",
            },
            timeout=10,
        )
    except requests.RequestException:
        raise OrderAllocationError("Ecommerce unreachable")

    if resp.status_code != 200:
        raise OrderAllocationError("Order not found")

    data = resp.json()
    items = data.get("items")

    if not isinstance(items, list) or not items:
        raise OrderAllocationError("Invalid order data")

    allocations = []

    for item in items:
        try:
            amount = Decimal(item["amount"])
        except (KeyError, InvalidOperation):
            raise OrderAllocationError("Invalid amount")

        allocations.append({
            "order_id": order_id,
            "seller_identifier": item["seller_identifier"],
            "amount": amount,
            "description": item.get("description", ""),
        })

    return allocations
