from wallet.models import Wallet
from django.shortcuts import render


def get_wallet_for_user(wallet_id_value, user):
    """
    Accept either wallet PK (UUID/int) or wallet.identifier (string).
    Ensure the wallet belongs to user or user is staff.
    Returns Wallet instance or raises Http404/PermissionDenied externally.
    """
    # Try primary key first
    wallet = None
    try:
        wallet = Wallet.objects.get(pk=wallet_id_value)
    except Exception:
        # fallback to identifier
        wallet = Wallet.objects.filter(identifier=wallet_id_value).first()

    if wallet is None:
        return None

    # permission: either owner or staff
    if getattr(user, 'is_staff', False) or getattr(wallet, 'owner', None) == user:
        return wallet
    return None

def wallet(request):
    context ={}
    return render(request, 'wallet.html', context)