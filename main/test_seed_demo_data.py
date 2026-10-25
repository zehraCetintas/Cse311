from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from main.management.commands.seed_demo_data import COURSES, DEMO_PASSWORD
from main.models import Course, ProgramOutcome, Student, StudentGrade, User
from main.services.calculator import POCalculator


def seed(*args):
    call_command("seed_demo_data", *args, stdout=StringIO())


class SeedDemoDataTestCase(TestCase):
    def test_creates_courses_users_students_and_grades(self):
        seed("--students", "10")

        self.assertEqual(ProgramOutcome.objects.count(), 11)
        self.assertEqual(Course.objects.count(), len(COURSES))
        self.assertEqual(Student.objects.count(), 10)
        self.assertTrue(StudentGrade.objects.exists())
        self.assertTrue(User.objects.get(username="demo_head").is_head())
        self.assertEqual(User.objects.filter(role=User.Role.INSTRUCTOR).count(), 2)

        # Every demo user can log in with the documented password
        self.assertTrue(User.objects.get(username="900001").check_password(DEMO_PASSWORD))
        self.assertTrue(User.objects.get(username="demo_instructor1").check_password(DEMO_PASSWORD))

    def test_assessment_weights_sum_to_100(self):
        seed("--students", "1")
        for course in Course.objects.all():
            total = sum(a.weight for a in course.assessments.all())
            self.assertEqual(total, 100, course.code)

    def test_students_get_po_scores(self):
        seed("--students", "5")
        student = Student.objects.get(student_number="900001")
        course = Course.objects.filter(assessments__student_grades__student=student).first()

        po_scores = POCalculator.calculate_student_po_scores_for_course(student, course)
        self.assertTrue(po_scores)
        for score in po_scores.values():
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_is_reproducible_and_rerunnable(self):
        seed("--students", "8")
        first = list(StudentGrade.objects.order_by("student__student_number", "assessment__course__code",
                                                   "assessment__name").values_list("score", flat=True))
        seed("--students", "8")
        second = list(StudentGrade.objects.order_by("student__student_number", "assessment__course__code",
                                                    "assessment__name").values_list("score", flat=True))

        self.assertEqual(first, second)
        self.assertEqual(Student.objects.count(), 8)

    def test_clear_removes_only_demo_data(self):
        real_student = Student.objects.create(student_number="220001", first_name="Real", last_name="Student")
        real_course = Course.objects.create(code="CSE 101", title="Intro")
        seed("--students", "3")

        seed("--clear")

        self.assertEqual(list(Student.objects.all()), [real_student])
        self.assertEqual(list(Course.objects.all()), [real_course])
        self.assertFalse(User.objects.filter(username__startswith="demo_").exists())

    def test_does_not_overwrite_real_course_with_same_code(self):
        Course.objects.create(code="CSE 311", title="Real course from Bologna")

        with self.assertRaises(CommandError):
            seed("--students", "3")

        self.assertEqual(Course.objects.get(code="CSE 311").title, "Real course from Bologna")
        self.assertFalse(Student.objects.exists())
