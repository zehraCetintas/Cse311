from django.test import TestCase
from django.urls import reverse

from main.models import (
    ProgramOutcome, Course, LearningOutcome,
    Assessment, AssessmentToLO, LOToPO, Student, StudentGrade, User
)
from main.services import analytics
from main.services.calculator import POCalculator


class AnalyticsDataMixin:
    def setUp(self):
        # Same worked example as POCalculatorTestCase / CourseReportTestCase
        self.po1 = ProgramOutcome.objects.create(code="PO1", title="PO 1", description="Desc 1")
        self.po2 = ProgramOutcome.objects.create(code="PO2", title="PO 2", description="Desc 2")
        # Not mapped to any course
        ProgramOutcome.objects.create(code="PO3", title="PO 3", description="Desc 3")
        # Mapped only to an excluded (ACU) course
        self.po4 = ProgramOutcome.objects.create(code="PO4", title="PO 4", description="Desc 4")

        self.course = Course.objects.create(code="CSE 311", title="Software")
        lo1 = LearningOutcome.objects.create(course=self.course, code="LO1", description="LO 1")
        lo2 = LearningOutcome.objects.create(course=self.course, code="LO2", description="LO 2")
        midterm = Assessment.objects.create(course=self.course, name="Midterm", weight=60.0)
        project = Assessment.objects.create(course=self.course, name="Project", weight=40.0)

        AssessmentToLO.objects.create(assessment=midterm, learning_outcome=lo1, weight=60.0)
        AssessmentToLO.objects.create(assessment=midterm, learning_outcome=lo2, weight=40.0)
        AssessmentToLO.objects.create(assessment=project, learning_outcome=lo1, weight=40.0)
        AssessmentToLO.objects.create(assessment=project, learning_outcome=lo2, weight=100.0)

        LOToPO.objects.create(learning_outcome=lo1, program_outcome=self.po1, weight=100.0)
        LOToPO.objects.create(learning_outcome=lo2, program_outcome=self.po1, weight=50.0)
        LOToPO.objects.create(learning_outcome=lo2, program_outcome=self.po2, weight=100.0)

        # Elif: PO1 = 84.95, PO2 = 82.86 / Can: PO1 = 45.05, PO2 = 47.14
        self.elif_ = Student.objects.create(student_number="1001", first_name="Elif", last_name="Cato")
        self.can = Student.objects.create(student_number="1002", first_name="Can", last_name="Yilmaz")
        for student, midterm_score, project_score in ((self.elif_, 90.0, 80.0), (self.can, 40.0, 50.0)):
            StudentGrade.objects.create(student=student, assessment=midterm, score=midterm_score)
            StudentGrade.objects.create(student=student, assessment=project, score=project_score)

        # University-wide (ACU) course: counted per student, excluded from department analytics
        self.acu_course = Course.objects.create(code="ACU 101", title="University Course")
        acu_lo = LearningOutcome.objects.create(course=self.acu_course, code="LO1", description="ACU LO")
        acu_final = Assessment.objects.create(course=self.acu_course, name="Final", weight=100.0)
        AssessmentToLO.objects.create(assessment=acu_final, learning_outcome=acu_lo, weight=100.0)
        LOToPO.objects.create(learning_outcome=acu_lo, program_outcome=self.po1, weight=100.0)
        LOToPO.objects.create(learning_outcome=acu_lo, program_outcome=self.po4, weight=100.0)
        StudentGrade.objects.create(student=self.elif_, assessment=acu_final, score=10.0)


class AnalyticsTestCase(AnalyticsDataMixin, TestCase):
    def test_course_scores_match_po_calculator(self):
        scores = analytics.compute_student_scores([self.course.pk])

        for student in (self.elif_, self.can):
            self.assertEqual(
                scores[student.pk]["courses"][self.course.pk]["po"],
                POCalculator.calculate_student_po_scores_for_course(student, self.course),
            )
        self.assertEqual(scores[self.elif_.pk]["courses"][self.course.pk]["po"], {"PO1": 84.95, "PO2": 82.86})

    def test_overall_po_score_is_weighted_across_courses(self):
        scores = analytics.compute_student_scores()

        # PO1: (84.95 * 150 + 10 * 100) / 250, LO-PO weights of both courses
        self.assertAlmostEqual(scores[self.elif_.pk]["po"]["PO1"], 54.97, places=2)
        self.assertEqual(scores[self.elif_.pk]["po"]["PO4"], 10.0)
        self.assertNotIn("PO4", scores[self.can.pk]["po"])

    def test_course_filter_ignores_other_courses(self):
        scores = analytics.compute_student_scores([self.course.pk])

        self.assertEqual(set(scores[self.elif_.pk]["courses"]), {self.course.pk})
        self.assertEqual(scores[self.elif_.pk]["po"]["PO1"], 84.95)

    def test_lo_without_grades_has_no_score(self):
        extra_lo = LearningOutcome.objects.create(course=self.course, code="LO3", description="LO 3")
        quiz = Assessment.objects.create(course=self.course, name="Quiz", weight=0.0)
        AssessmentToLO.objects.create(assessment=quiz, learning_outcome=extra_lo, weight=100.0)

        scores = analytics.compute_student_scores([self.course.pk])

        self.assertIsNone(scores[self.elif_.pk]["courses"][self.course.pk]["lo"][extra_lo.pk])

    def test_department_averages_exclude_acu_courses(self):
        self.assertEqual(analytics.department_po_averages(), {"PO1": 65.0, "PO2": 65.0})

    def test_po_course_breakdown(self):
        breakdown = analytics.po_course_breakdown("PO1")

        self.assertEqual(breakdown["dept_average"], 65.0)
        self.assertEqual(len(breakdown["rows"]), 1)
        row = breakdown["rows"][0]
        self.assertEqual(row["course"], self.course)
        self.assertEqual(row["student_count"], 2)
        self.assertEqual(row["average"], 65.0)
        self.assertEqual(row["lowest"], 45.05)
        self.assertEqual(row["below_threshold"], 1)
        self.assertEqual(row["difference"], 0.0)
        self.assertEqual([lo["code"] for lo in row["los"]], ["LO1", "LO2"])

    def test_po_course_breakdown_sorts_lowest_average_first(self):
        weak_course = Course.objects.create(code="CSE 321", title="Data Systems")
        lo = LearningOutcome.objects.create(course=weak_course, code="LO1", description="LO 1")
        final = Assessment.objects.create(course=weak_course, name="Final", weight=100.0)
        AssessmentToLO.objects.create(assessment=final, learning_outcome=lo, weight=100.0)
        LOToPO.objects.create(learning_outcome=lo, program_outcome=self.po1, weight=100.0)
        StudentGrade.objects.create(student=self.can, assessment=final, score=20.0)

        rows = analytics.po_course_breakdown("PO1")["rows"]

        self.assertEqual([row["course"] for row in rows], [weak_course, self.course])
        self.assertEqual(rows[0]["below_threshold"], 1)

    def test_uncovered_pos(self):
        self.assertEqual([po.code for po in analytics.uncovered_pos()], ["PO3", "PO4"])


class PODetailViewTestCase(AnalyticsDataMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.head = User.objects.create_user(
            username="head", password="test-password", role=User.Role.HEAD_OF_FACULTY
        )
        self.instructor = User.objects.create_user(
            username="instructor", password="test-password", role=User.Role.INSTRUCTOR
        )

    def test_head_of_faculty_sees_course_breakdown(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("po_detail", args=["PO1"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["outcome"], self.po1)
        self.assertEqual(response.context["dept_average"], 65.0)
        self.assertFalse(response.context["is_uncovered"])
        self.assertContains(response, "CSE 311")

    def test_uncovered_po_is_flagged(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("po_detail", args=["PO3"]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_uncovered"])

    def test_other_roles_are_forbidden(self):
        self.client.force_login(self.instructor)

        response = self.client.get(reverse("po_detail", args=["PO1"]))

        self.assertEqual(response.status_code, 403)

    def test_unknown_po_returns_404(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("po_detail", args=["PO99"]))

        self.assertEqual(response.status_code, 404)
