from getpass import getpass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from accounts.services import UsernameConflictError, create_user


class Command(BaseCommand):
    help = "Create the first business ADMIN account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=True,
            help="Username for the first business ADMIN.",
        )

    def handle(self, *args, **options):
        if User.objects.filter(role="ADMIN").exists():
            raise CommandError("A business ADMIN already exists.")

        password = getpass("Password: ")
        password_confirmation = getpass("Password (again): ")

        if password != password_confirmation:
            raise CommandError("Passwords do not match.")

        try:
            user = create_user(
                username=options["username"],
                password=password,
                role="ADMIN",
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        except UsernameConflictError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Business ADMIN '{user.username}' created successfully."
            )
        )
