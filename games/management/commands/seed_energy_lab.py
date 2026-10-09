from django.core.management.base import BaseCommand
from django.db import transaction

from games.content import load_default


class Command(BaseCommand):
    help = "Load (or refresh) the ENERGY LAB LIVE missions and questions from fixtures/energy_lab.json."

    def handle(self, *args, **options):
        with transaction.atomic():
            experience, counts = load_default()
        self.stdout.write(
            self.style.SUCCESS(
                f"{experience.title}: {counts['missions']} missions, {counts['questions']} questions loaded."
            )
        )
