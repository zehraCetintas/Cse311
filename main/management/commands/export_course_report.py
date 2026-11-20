from django.core.management.base import BaseCommand, CommandError

from main.models import Course
from main.services.report_generator import CourseReportService


class Command(BaseCommand):
    help = "Exports a course outcome report (LO/PO scores, achievement rates, at-risk students) as an Excel file."

    def add_arguments(self, parser):
        parser.add_argument("course_code", help='Course code, e.g. "CSE 311"')
        parser.add_argument(
            "--threshold",
            type=float,
            default=CourseReportService.DEFAULT_THRESHOLD,
            help="Success threshold for LO/PO scores (default: 60)",
        )
        parser.add_argument("--output", help="Output .xlsx path (default: <course code>_report.xlsx)")

    def handle(self, *args, **options):
        try:
            course = Course.objects.get(code=options["course_code"])
        except Course.DoesNotExist:
            raise CommandError(f"Course '{options['course_code']}' does not exist.")

        output_path = options["output"] or f"{course.code.replace(' ', '_')}_report.xlsx"
        report_file = CourseReportService.export_excel(course, options["threshold"])
        with open(output_path, "wb") as f:
            f.write(report_file.getvalue())

        self.stdout.write(self.style.SUCCESS(f"Report for {course.code} saved to {output_path}"))
