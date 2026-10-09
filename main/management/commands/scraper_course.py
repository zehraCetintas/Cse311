import re

from django.core.management.base import BaseCommand
from main.services.bologna_scraper import BolognaScraperService


class Command(BaseCommand):
    help = "Scrape a course syllabus from an Acibadem OBS program or course URL."

    def add_arguments(self, parser):
        parser.add_argument("url", type=str, help="The target Bologna syllabus URL")
        parser.add_argument(
            "--course-code",
            default=None,
            help="Optionally scrape only this course from a curriculum URL",
        )

    def handle(self, *args, **options):
        url = options["url"]
        self.stdout.write(f"Scraping from: {url}")

        result = BolognaScraperService.scrape_course_data(
            url, course_code=options["course_code"]
        )

        if not result["success"]:
            self.stdout.write(self.style.ERROR(f"Error: {result['error']}"))
            return

        is_batch = "courses" in result
        courses = result["courses"] if is_batch else [result["data"]]
        for data in courses:
            self._display_course(data)

        synced_courses = BolognaScraperService.sync_to_database(result)
        if is_batch:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully synced {len(synced_courses)} courses to database!"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully synced {synced_courses.code} to database!"
                )
            )

    def _display_course(self, data):
        self.stdout.write(
            self.style.SUCCESS(
                f"Found Course: {data['course_code']} - {data['course_title']}"
            )
        )
        self.stdout.write(f"Learning Outcomes Found: {len(data['learning_outcomes'])}")
        for lo in data["learning_outcomes"]:
            self.stdout.write(f"  - {lo}")

        self.stdout.write(f"Assessments Found: {len(data['assessments'])}")
        for asm in data["assessments"]:
            quantity = f", quantity {asm['quantity']}" if "quantity" in asm else ""
            self.stdout.write(
                f"  - {asm['name']}: contribution {asm['weight']}%{quantity}"
            )

        for assessment_type, pattern in (
            ("Midterm", r"\bmid[\s-]*term\b"),
            ("Project", r"\bproject\b"),
            ("Final", r"\bfinal\b"),
        ):
            found = any(
                re.search(pattern, asm["name"], re.IGNORECASE)
                for asm in data["assessments"]
            )
            if not found:
                self.stdout.write(f"  - {assessment_type}: not found")