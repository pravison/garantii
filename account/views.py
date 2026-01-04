from django.contrib.auth import authenticate, get_user_model

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.throttling import UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .serializers import RegistrationSerializer
from .utils import format_kenyan_phone_number

# Throttle class to prevent mass signups
class RegisterThrottle(UserRateThrottle):
    rate = "5/min"

# CSRF exemption applied correctly to class-based view
@method_decorator(csrf_exempt, name='dispatch')
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [RegisterThrottle]

    def post(self, request, *args, **kwargs):
        serializer = RegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()

            
            return Response(
                {
                    "message": "Account created successfully",
                },
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


User = get_user_model()

class LoginThrottle(UserRateThrottle):
    rate = "10/min"

@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request, *args, **kwargs):
        phone_raw = request.data.get('username')  # username is phone number
        password = request.data.get('password')

        if not phone_raw or not password:
            return Response(
                {"detail": "Phone number and password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            username = format_kenyan_phone_number(phone_raw)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Check if a user with this phone number exists
        if not User.objects.filter(username=username).exists():
            return Response(
                {"detail": "The submitted phone number is not recognized."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Authenticate user
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail":"Invalid password."}, status=status.HTTP_401_UNAUTHORIZED)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "is_staff": user.is_staff,
            "user": {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": user.username,  # assuming phone is username
            }
        }, status=status.HTTP_200_OK)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Logged out successfully."}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
