from django.urls import path
from .views import *

urlpatterns = [
    path('', wallet, name='wallet'),
    path("transactions/", escrow_transactions, name="escrow_transactions"),
    path('wallets/api/', UserWalletsView.as_view(), name='user-wallets'),
    path('wallets/create/api/', WalletCreateView.as_view(), name='wallet-create'),
    path("payments/wallet-transactions/", WalletPaymentListView.as_view(), name="wallet-transactions"),
    path('api/escrow/wallet-transactions/', WalletEscrowListView.as_view(), name='wallet-escrow-list'),
    path('api/escrow/request-reversal/<uuid:escrow_id>/', EscrowRequestReversalView.as_view(), name='escrow-request-reversal'),
    path('api/escrow/add-extra/<uuid:escrow_id>/', EscrowAddExtraInfoView.as_view(), name='escrow-add-extra'),
    path("api/testimonials/", ApprovedTestimonialListView.as_view(), name="testimonial-list"),
    path("api/testimonials/add/", AddTestimonialView.as_view(), name="testimonial-add"),
    path("api/feedback/add/", AddCustomerFeedbackView.as_view(), name="customer-feedback-add"),

    # mpesa call back url for c2b
     path("api/c2b-callback-url/", MpesaC2BConfirmationView.as_view(), name="c2b-callback-url"),

]