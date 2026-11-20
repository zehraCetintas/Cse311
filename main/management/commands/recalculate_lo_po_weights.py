from django.core.management.base import BaseCommand

from main.models import Course
from main.services.po_matcher import map_course_los_to_pos


class Command(BaseCommand):
    help = "Recalculates LO-to-PO weights for all courses and their learning outcomes."

    def handle(self, *args, **options):
        course_count = 0
        outcome_count = 0
        for course in Course.objects.iterator(chunk_size=200):
            mappings = map_course_los_to_pos(course)
            course_count += 1
            outcome_count += len(mappings)

        self.stdout.write(
            self.style.SUCCESS(
                f"Recalculated mappings for {outcome_count} learning outcomes "
                f"across {course_count} courses."
            )
        )
