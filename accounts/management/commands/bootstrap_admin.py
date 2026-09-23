from getpass import getpass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

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
            with transaction.atomic():
                # Serialize concurrent bootstrap commands on PostgreSQL.
                # Hold the transaction-level lock only after password input.
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(%s, %s)",
                        [2026, 12],
                    )

                # A check before prompting is only an optimization. This
                # second check is authoritative because it holds the lock.
                if User.objects.filter(role="ADMIN").exists():
                    raise CommandError("A business ADMIN already exists.")

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
