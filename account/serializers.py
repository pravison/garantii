from django.contrib.auth.models import User
from rest_framework import serializers
from .utils import format_kenyan_phone_number

class RegistrationSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(required=True)
    last_name = serializers.CharField(required=True)
    email = serializers.EmailField(required=True)
    phone_number = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number", "password"]

    def validate_phone_number(self, value):
        """
        Validate & normalize phone number using your formatter.
        If invalid -> show error.
        """
        try:
            formatted = format_kenyan_phone_number(value)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

        # Check uniqueness using formatted number
        if User.objects.filter(username=formatted).exists():
            raise serializers.ValidationError("Phone number already registered.")

        return formatted

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered.")
        return value

    def create(self, validated_data):
        user = User(
            username=validated_data["phone_number"],  # already formatted
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            email=validated_data["email"]
        )
        user.set_password(validated_data["password"])
        user.save()
        return user
