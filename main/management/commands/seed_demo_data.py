import random

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from main.models import (
    Assessment, AssessmentToLO, Course, LearningOutcome, LOToPO,
    ProgramOutcome, Student, StudentGrade, User,
)


DEMO_PASSWORD = "demo12345"
DEMO_STUDENT_PREFIX = "9"  # Demo student numbers look like 900001, 900002, ...

HEAD = {"username": "demo_head", "first_name": "Ahmet", "last_name": "Yildirim"}
INSTRUCTORS = [
    {"username": "demo_instructor1", "first_name": "Selin", "last_name": "Aksoy"},
    {"username": "demo_instructor2", "first_name": "Murat", "last_name": "Ozkan"},
]

# Course structure: learning outcomes, assessments (weights sum to 100),
# assessment -> LO contributions and LO -> PO contributions (percentages).
COURSES = [
    {
        "code": "CSE 211",
        "title": "Data Structures",
        "instructor": 0,
        "los": {
            "LO1": "Analyze the time and space complexity of algorithms.",
            "LO2": "Implement linear and non-linear data structures.",
            "LO3": "Choose an appropriate data structure for a given problem.",
        },
        "assessments": {
            "Midterm": (35, {"LO1": 60, "LO2": 40}),
            "Homework": (25, {"LO2": 100}),
            "Final": (40, {"LO1": 40, "LO2": 30, "LO3": 100}),
        },
        "po_map": {"LO1": {"PO1": 100}, "LO2": {"PO2": 100, "PO4": 50}, "LO3": {"PO2": 50, "PO3": 100}},
    },
    {
        "code": "CSE 311",
        "title": "Software",
        "instructor": 0,
        "los": {
            "LO1": "Apply agile software development practices.",
            "LO2": "Design, test and deliver a web application as a team.",
            "LO3": "Use version control, CI and CD tools effectively.",
        },
        "assessments": {
            "Midterm 1": (20, {"LO1": 100}),
            "Midterm 2": (20, {"LO1": 50, "LO3": 50}),
            "Project": (40, {"LO2": 100, "LO3": 100}),
            "Presentation": (20, {"LO2": 40}),
        },
        "po_map": {
            "LO1": {"PO10": 100, "PO8": 50},
            "LO2": {"PO3": 100, "PO6": 100, "PO7": 50},
            "LO3": {"PO4": 100},
        },
    },
    {
        "code": "CSE 321",
        "title": "Data Systems",
        "instructor": 1,
        "los": {
            "LO1": "Design normalized relational data models.",
            "LO2": "Write efficient queries and use indexes and transactions.",
            "LO3": "Design scalable and fault-tolerant data architectures.",
        },
        "assessments": {
            "Midterm 1": (20, {"LO1": 100}),
            "Midterm 2": (20, {"LO2": 100}),
            "Project": (40, {"LO1": 40, "LO2": 60, "LO3": 100}),
            "Quiz": (20, {"LO2": 40}),
        },
        "po_map": {
            "LO1": {"PO1": 50, "PO3": 100},
            "LO2": {"PO2": 100, "PO5": 50},
            "LO3": {"PO3": 50, "PO11": 30},
        },
    },
    {
        "code": "MAT 241",
        "title": "Linear Algebra",
        "instructor": 1,
        "los": {
            "LO1": "Solve systems of linear equations using matrices.",
            "LO2": "Compute eigenvalues and eigenvectors and interpret them.",
        },
        "assessments": {
            "Midterm": (40, {"LO1": 100, "LO2": 20}),
            "Final": (60, {"LO1": 50, "LO2": 100}),
        },
        "po_map": {"LO1": {"PO1": 100}, "LO2": {"PO1": 100, "PO5": 50}},
    },
]

FIRST_NAMES = [
    "Elif", "Can", "Zeynep", "Mert", "Ayse", "Burak", "Deniz", "Ece", "Emre", "Selin",
    "Kerem", "Defne", "Arda", "Ilayda", "Onur", "Melis", "Baris", "Nehir", "Kaan", "Irem",
]
LAST_NAMES = [
    "Yilmaz", "Kaya", "Demir", "Sahin", "Celik", "Yildiz", "Aydin", "Ozturk", "Arslan", "Dogan",
    "Kilic", "Aslan", "Cetin", "Koc", "Kurt", "Ozdemir", "Polat", "Erdem", "Gunes", "Tekin",
]


class Command(BaseCommand):
    help = (
        "Creates reproducible demo data: courses with learning outcomes, assessments and "
        "PO mappings, a department head, instructors, students and grades. "
        "Running it again replaces the previous demo data; other data is not touched."
    )

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=40, help="Number of demo students (default: 40)")
        parser.add_argument("--seed", type=int, default=311, help="Random seed (default: 311)")
        parser.add_argument("--clear", action="store_true", help="Only delete existing demo data")

    def handle(self, *args, **options):
        rng = random.Random(options["seed"])

        with transaction.atomic():
            self._clear()
            if options["clear"]:
                self.stdout.write(self.style.SUCCESS("Demo data deleted."))
                return
            self._check_no_real_course_conflicts()

            call_command("load_program_outcomes", stdout=self.stdout)
            program_outcomes = {po.code: po for po in ProgramOutcome.objects.all()}

            password = make_password(DEMO_PASSWORD)
            User.objects.create(role=User.Role.HEAD_OF_FACULTY, password=password, **HEAD)
            instructors = [
                User.objects.create(role=User.Role.INSTRUCTOR, password=password, **data)
                for data in INSTRUCTORS
            ]

            courses = [
                self._create_course(data, instructors[data["instructor"]], program_outcomes)
                for data in COURSES
            ]
            grade_count = self._create_students(rng, options["students"], courses, password)

        self.stdout.write(self.style.SUCCESS(
            f"Demo data created: {len(courses)} courses, {options['students']} students, "
            f"{grade_count} grades. Password for all demo users: {DEMO_PASSWORD}"
        ))

    def _clear(self):
        demo_codes = [data["code"] for data in COURSES]
        demo_students = Student.objects.filter(student_number__startswith=DEMO_STUDENT_PREFIX)
        demo_usernames = [HEAD["username"]] + [data["username"] for data in INSTRUCTORS]

        # Only courses taught by demo instructors are demo courses. A real course with the
        # same code (e.g. imported from Bologna) is never deleted.
        Course.objects.filter(code__in=demo_codes, instructor__username__in=demo_usernames).delete()
        User.objects.filter(student_profile__in=demo_students).delete()
        demo_students.delete()
        User.objects.filter(username__in=demo_usernames).delete()

    @staticmethod
    def _check_no_real_course_conflicts():
        demo_codes = [data["code"] for data in COURSES]
        existing = list(Course.objects.filter(code__in=demo_codes).values_list("code", flat=True))
        if existing:
            raise CommandError(
                f"Non-demo course(s) already exist with code(s) {', '.join(existing)}. "
                "Demo data was not created so that real data is not overwritten."
            )

    def _create_course(self, data, instructor, program_outcomes):
        course = Course.objects.create(code=data["code"], title=data["title"], instructor=instructor)
        los = {
            code: LearningOutcome.objects.create(course=course, code=code, description=description)
            for code, description in data["los"].items()
        }
        for name, (weight, lo_weights) in data["assessments"].items():
            assessment = Assessment.objects.create(course=course, name=name, weight=weight)
            for lo_code, lo_weight in lo_weights.items():
                AssessmentToLO.objects.create(
                    assessment=assessment, learning_outcome=los[lo_code], weight=lo_weight
                )
        for lo_code, po_weights in data["po_map"].items():
            for po_code, po_weight in po_weights.items():
                LOToPO.objects.create(
                    learning_outcome=los[lo_code],
                    program_outcome=program_outcomes[po_code],
                    weight=po_weight,
                )
        return course

    def _create_students(self, rng, count, courses, password):
        grades = []
        for index in range(1, count + 1):
            number = f"{DEMO_STUDENT_PREFIX}{index:05d}"
            first_name = rng.choice(FIRST_NAMES)
            last_name = rng.choice(LAST_NAMES)
            user = User.objects.create(
                username=number, first_name=first_name, last_name=last_name,
                role=User.Role.STUDENT, password=password,
            )
            student = Student.objects.create(
                student_number=number, first_name=first_name, last_name=last_name, user=user,
            )

            # Each student has an overall ability; individual grades vary around it,
            # so PO profiles look realistic (some strong, some at-risk students).
            ability = min(max(rng.gauss(68, 15), 25), 98)
            taken = rng.sample(courses, rng.randint(2, len(courses)))
            self._enroll(student, taken)
            for course in taken:
                course_bias = rng.uniform(-8, 8)
                for assessment in course.assessments.all():
                    score = round(min(max(rng.gauss(ability + course_bias, 9), 0), 100))
                    grades.append(StudentGrade(student=student, assessment=assessment, score=score))

        StudentGrade.objects.bulk_create(grades)
        return len(grades)

    @staticmethod
    def _enroll(student, courses):
        # Student.enrolled_courses and Student.department come with the core-ui branch;
        # fill them only when the model has them.
        if hasattr(student, "enrolled_courses"):
            student.enrolled_courses.add(*courses)
        if hasattr(student, "department"):
            student.faculty = "Faculty of Engineering and Natural Sciences"
            student.department = "Computer Engineering"
            student.save()
