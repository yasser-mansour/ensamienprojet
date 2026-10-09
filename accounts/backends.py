from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailHostBackend(ModelBackend):
    """
    Authenticate the host by e-mail address + password.

    Only active staff accounts may sign in: team participants never have Django
    users, so every authenticated user of this application is a host.
    """

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        email = (email or username or "").strip()
        if not email or not password:
            return None
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            User().set_password(password)  # equalise timing with the found-user path
            return None
        except User.MultipleObjectsReturned:
            return None
        if user.check_password(password) and self.user_can_authenticate(user) and user.is_staff:
            return user
        return None
