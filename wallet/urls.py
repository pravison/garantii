from django.urls import path
from .views import *

urlpatterns = [
    path('', wallet, name='wallet'),
    path('wallets/api/', UserWalletsView.as_view(), name='user-wallets'),
    path('wallets/create/api/', WalletCreateView.as_view(), name='wallet-create'),
    path("payments/wallet-transactions/", WalletPaymentListView.as_view(), name="wallet-transactions"),
    path('api/escrow/wallet-transactions/', WalletEscrowListView.as_view(), name='wallet-escrow-list'),
    path('api/escrow/request-reversal/<uuid:escrow_id>/', EscrowRequestReversalView.as_view(), name='escrow-request-reversal'),
    path('api/escrow/add-extra/<uuid:escrow_id>/', EscrowAddExtraInfoView.as_view(), name='escrow-add-extra'),
    path("api/testimonials/", ApprovedTestimonialListView.as_view(), name="testimonial-list"),
    path("api/testimonials/add/", AddTestimonialView.as_view(), name="testimonial-add"),
    path("api/feedback/add/", AddCustomerFeedbackView.as_view(), name="customer-feedback-add"),

    path("verify-pin/", VerifyPinView.as_view()),
    path('pin/set/', SetPinView.as_view(), name='set-pin'),
    path('pin/verify-otp/', VerifyPinOTPView.as_view(), name='verify-pin-otp'),
    path('pin/resend-otp/', ResendPinOTPView.as_view(), name='resend-pin-otp'),
    
    path("withdrawals/preview/", withdrawal_preview, name="withdrawal-preview"),
    path("withdrawals/confirm/", withdrawal_confirm, name="withdrawal-confirm"),

]