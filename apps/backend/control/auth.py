from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


class DemoBackend(BaseBackend):
    def authenticate(self, request, email=None, password=None, **kwargs):
        if not isinstance(email, str) or not isinstance(password, str):
            return None
        email = email.strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            return None
        if email.rsplit("@", 1)[-1] != "clemson.edu" or len(email) > 150:
            return None
        encoded = settings.CONTROL_PASSWORD_HASH
        if not encoded or not check_password(password or "", encoded):
            return None
        user, created = User.objects.get_or_create(username=email, defaults={"email": email})
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user if user.is_active and not user.is_staff and not user.is_superuser else None

    def get_user(self, user_id):
        return User.objects.filter(pk=user_id, is_active=True).first()
