from django.core.management.base import BaseCommand
from main.models import ProgramOutcome


class Command(BaseCommand):
    help = "Loads the 11 official Program Outcomes into the database."

    def handle(self, *args, **options):
        outcomes = [
            {
                "code": "PO1",
                "title": "Math, Science & Engineering Knowledge",
                "description": "Gain adequate knowledge in mathematics, science and related engineering discipline subjects; ability to use theoretical and applied knowledge in these fields in complex engineering problems.",
            },
            {
                "code": "PO2",
                "title": "Problem Formulation & Solution",
                "description": "Gain ability to identify, formulate and solve complex engineering problems; gain ability to choose and apply appropriate analysis and modeling methods for this purpose.",
            },
            {
                "code": "PO3",
                "title": "System & Product Design",
                "description": "Gain ability to design a complex system, process, device or product to meet certain requirements under realistic constraints and conditions; ability to apply modern design methods for this purpose.",
            },
            {
                "code": "PO4",
                "title": "Modern Tools & IT",
                "description": "Analyze and create solutions to complex problems encountered in engineering applications of modern techniques and tools for development, have skills, gain the ability to use information technology effectively.",
            },
            {
                "code": "PO5",
                "title": "Experimentation & Data Analysis",
                "description": "Gain ability to design experiments, conduct experiments, collect data, analyze and interpret results for the study of complex engineering problems or discipline-specific research topics.",
            },
            {
                "code": "PO6",
                "title": "Teamwork & Individual Work",
                "description": "Gain ability to work effectively in interdisciplinary and multidisciplinary teams; work individually.",
            },
            {
                "code": "PO7",
                "title": "Communication Skills",
                "description": "Gain ability to communicate effectively in Turkish oral and written; knowledge of at least one foreign language; ability to write effective reports and understand written report, design and production reports, make effective presentations, give and receive clear and understandable instructions.",
            },
            {
                "code": "PO8",
                "title": "Lifelong Learning",
                "description": "Gain awareness of the need for lifelong learning; the ability to access information, monitor developments in science and technology, and constantly renew oneself.",
            },
            {
                "code": "PO9",
                "title": "Ethics & Professional Responsibility",
                "description": "Act in accordance with ethical principles, awareness of professional and ethical responsibility; gain knowledge of standards used in engineering applications.",
            },
            {
                "code": "PO10",
                "title": "Project Management & Entrepreneurship",
                "description": "Gain knowledge of business practices such as Project Management, risk Management and change management; gain awareness about entrepreneurship, innovation; have information about sustainable development.",
            },
            {
                "code": "PO11",
                "title": "Health, Environment & Legal Dimensions",
                "description": "Gain knowledge of the effects of engineering practices on health, environment and safety in universal and social dimensions and the problems reflected in the field of engineering of the era; gain awareness of the legal consequences of engineering solutions.",
            },
        ]

        created_count = 0
        for item in outcomes:
            obj, created = ProgramOutcome.objects.get_or_create(
                code=item["code"],
                defaults={
                    "title": item["title"],
                    "description": item["description"],
                },
            )
            if created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully loaded {created_count} new Program Outcomes."
            )
        )