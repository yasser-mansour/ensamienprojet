import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Create or update the ENSAMien host (administrator) account. "
        "The password is read interactively, or from HOST_PASSWORD for non-interactive use."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--no-input", action="store_true", help="Read the password from HOST_PASSWORD.")

    def handle(self, *args, email, no_input, **options):
        email = email.strip().lower()
        if "@" not in email:
            raise CommandError("Provide a valid e-mail address.")

        if no_input:
            password = os.environ.get("HOST_PASSWORD", "")
            if not password:
                raise CommandError("HOST_PASSWORD is not set.")
        else:
            password = getpass.getpass("Host password: ")
            if password != getpass.getpass("Repeat password: "):
                raise CommandError("Passwords do not match.")

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first() or User(username=email, email=email)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages))

        created = user.pk is None
        user.username = email
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Host account {'created' if created else 'updated'}: {email}"))
