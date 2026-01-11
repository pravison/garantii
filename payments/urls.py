from django.urls import path
from .views import *

urlpatterns = [
    # mpesa call back url for c2b
    path("api/c2b-validation-url/", MpesaC2BValidationView.as_view(), name="c2b-validation-url"),
    path("api/c2b-confirmation-url/", MpesaC2BConfirmationView.as_view(), name="c2b-confirmation-url"),


# b2c
    

]