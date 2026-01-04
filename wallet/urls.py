from django.urls import path
from .views import *

urlpatterns = [
    path('', wallet, name='wallet'),
    path('escrow-product-flow/', escrowProductFlow, name='escrow-product-flow'),
    path('escrow/update-flow/', update_product_flow, name='update_product_flow'),
    
    path('escrow-reversal-requests/', escrowReversalRequests, name='escrow-reversal-requests'),
    path('escrow-reversal-action/', escrow_reversal_action, name='escrow-reversal-action'),
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

    #stk push 
    path("stk_push/initiate/", initiate_stk_push, name="initiate_stk_push"),

    # Callback URL that Safaricom calls when STK Push is completed
    path("stk_push/callback/", STKPushCallbackView.as_view(), name="stk_push_callback"),
    path("stk_push/status/", stk_push_status, name="stk_push_status"),
]