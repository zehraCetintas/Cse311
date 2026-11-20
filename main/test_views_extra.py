from io import StringIO
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from main.models import (
    ProgramOutcome, Course, LearningOutcome,
    Assessment, AssessmentToLO, LOToPO, Student, StudentGrade, User
)
from main.services.bologna_scraper import BolognaScraperService
from main.services.calculator import POCalculator

OBS_URL = "https://obs.acibadem.edu.tr/course.aspx"


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def last_message(response):
    # Messages pile up across requests that are not followed, so loops
    # only look at the message the latest request added.
    return messages_of(response)[-1]


class BolognaImportViewTestCase(TestCase):
    def setUp(self):
        self.head = User.objects.create_user(
            username="head", password="test-password", role=User.Role.HEAD_OF_FACULTY
        )
        self.client.force_login(self.head)
        self.url = reverse("import_bologna_course")

    @patch.object(BolognaScraperService, "scrape_course_data")
    def test_rejects_urls_outside_acibadem_obs(self, scrape_course_data):
        for url in ("", "ftp://obs.acibadem.edu.tr/x", "https://example.com/course.aspx"):
            with self.subTest(url=url):
                response = self.client.post(self.url, {"syllabus_url": url})

                self.assertRedirects(response, reverse("head_dashboard"), fetch_redirect_response=False)
                self.assertEqual(last_message(response), "Enter a valid Bologna syllabus URL from obs.acibadem.edu.tr.")
        scrape_course_data.assert_not_called()

    @patch.object(BolognaScraperService, "scrape_course_data")
    def test_reports_scraper_error(self, scrape_course_data):
        scrape_course_data.return_value = {"success": False, "error": "Page not reachable"}

        response = self.client.post(self.url, {"syllabus_url": OBS_URL})

        self.assertEqual(messages_of(response), ["Course import failed: Page not reachable"])

    @patch.object(BolognaScraperService, "sync_to_database", side_effect=ValueError("Duplicate course code"))
    @patch.object(BolognaScraperService, "scrape_course_data", return_value={"success": True})
    def test_reports_sync_error(self, scrape_course_data, sync_to_database):
        response = self.client.post(self.url, {"syllabus_url": OBS_URL})

        self.assertEqual(messages_of(response), ["Course import failed: Duplicate course code"])

    @patch.object(BolognaScraperService, "sync_to_database", return_value=[])
    @patch.object(BolognaScraperService, "scrape_course_data", return_value={"success": True})
    def test_reports_when_nothing_was_synced(self, scrape_course_data, sync_to_database):
        response = self.client.post(self.url, {"syllabus_url": OBS_URL})

        self.assertEqual(messages_of(response), ["Course import failed: no courses were synchronized."])

    @patch.object(BolognaScraperService, "sync_to_database")
    @patch.object(BolognaScraperService, "scrape_course_data", return_value={"success": True})
    def test_batch_import_saves_syllabus_url_on_every_course(self, scrape_course_data, sync_to_database):
        courses = [
            Course.objects.create(code="CSE 101", title="Intro"),
            Course.objects.create(code="CSE 102", title="Programming"),
        ]
        sync_to_database.return_value = courses

        response = self.client.post(self.url, {"syllabus_url": OBS_URL})

        self.assertEqual(
            messages_of(response),
            ["Imported 2 courses; assign instructors in the workspace below."],
        )
        for course in courses:
            course.refresh_from_db()
            self.assertEqual(course.syllabus_url, OBS_URL)


class AssignCourseInstructorViewTestCase(TestCase):
    def setUp(self):
        self.head = User.objects.create_user(
            username="head", password="test-password", role=User.Role.HEAD_OF_FACULTY
        )
        self.instructor = User.objects.create_user(
            username="instructor", password="test-password", role=User.Role.INSTRUCTOR
        )
        self.course = Course.objects.create(code="CSE 311", title="Software", instructor=self.instructor)
        self.client.force_login(self.head)
        self.url = reverse("assign_course_instructor")

    def post(self, **data):
        return self.client.post(self.url, data)

    def test_rejects_invalid_course(self):
        self.assertEqual(messages_of(self.post(course_id="abc")), ["Choose a valid course."])
        self.assertEqual(self.post(course_id="9999").status_code, 404)

    def test_rejects_invalid_or_inactive_instructor(self):
        inactive = User.objects.create_user(
            username="inactive", password="test-password", role=User.Role.INSTRUCTOR, is_active=False
        )
        student = User.objects.create_user(
            username="student", password="test-password", role=User.Role.STUDENT
        )

        self.assertEqual(
            last_message(self.post(course_id=self.course.pk, instructor_id="x")),
            "Choose a valid instructor.",
        )
        for user in (inactive, student):
            with self.subTest(user=user.username):
                self.assertEqual(
                    last_message(self.post(course_id=self.course.pk, instructor_id=user.pk)),
                    "Choose a registered active instructor.",
                )
        self.course.refresh_from_db()
        self.assertEqual(self.course.instructor, self.instructor)

    def test_empty_instructor_unassigns_course(self):
        response = self.post(course_id=self.course.pk, instructor_id="")

        self.assertEqual(messages_of(response), ["CSE 311 is now unassigned."])
        self.course.refresh_from_db()
        self.assertIsNone(self.course.instructor)


class GradeUploadValidationTestCase(TestCase):
    def setUp(self):
        self.instructor = User.objects.create_user(
            username="instructor", password="test-password", role=User.Role.INSTRUCTOR
        )
        self.course = Course.objects.create(code="CSE 311", title="Software", instructor=self.instructor)
        self.assessment = Assessment.objects.create(course=self.course, name="Midterm", weight=40)
        self.client.force_login(self.instructor)
        self.url = reverse("upload_grades")
        self.dashboard = f"{reverse('instructor_dashboard')}?course_id={self.course.pk}"

    def test_rejects_missing_or_invalid_assessment(self):
        for assessment_id in ("", "abc"):
            with self.subTest(assessment_id=assessment_id):
                response = self.client.post(self.url, {"assessment_id": assessment_id})
                self.assertEqual(last_message(response), "Choose a valid assessment.")

    def test_requires_a_file(self):
        response = self.client.post(self.url, {"assessment_id": self.assessment.pk})

        self.assertRedirects(response, self.dashboard, fetch_redirect_response=False)
        self.assertEqual(messages_of(response), ["Choose an Excel (.xlsx) file to upload."])

    def test_rejects_files_that_are_not_xlsx(self):
        grades_file = SimpleUploadedFile("grades.csv", b"student_number,score\n1001,90\n")

        response = self.client.post(self.url, {"assessment_id": self.assessment.pk, "grades_file": grades_file})

        self.assertEqual(messages_of(response), ["Only Excel .xlsx files are supported."])

    def test_reports_a_broken_xlsx_file_without_saving_grades(self):
        grades_file = SimpleUploadedFile("grades.xlsx", b"this is not a real Excel file")

        response = self.client.post(self.url, {"assessment_id": self.assessment.pk, "grades_file": grades_file})

        [message] = messages_of(response)
        self.assertTrue(message.startswith("Grade import failed; no grades were saved:"))
        self.assertFalse(StudentGrade.objects.exists())


class StudentDashboardForStaffTestCase(TestCase):
    def setUp(self):
        self.instructor = User.objects.create_user(
            username="instructor", password="test-password", role=User.Role.INSTRUCTOR
        )
        self.student = Student.objects.create(student_number="1001", first_name="Elif", last_name="Cato")
        self.client.force_login(self.instructor)

    def test_staff_without_student_id_see_student_picker(self):
        response = self.client.get(reverse("student_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_student"])
        self.assertEqual(list(response.context["students"]), [self.student])
        self.assertEqual(response.context["po_scores"], [None] * 11)

    def test_staff_can_open_a_students_dashboard(self):
        response = self.client.get(reverse("student_dashboard"), {"student_id": self.student.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_student"], self.student)

    def test_unknown_student_returns_404(self):
        response = self.client.get(reverse("student_dashboard"), {"student_id": 9999})

        self.assertEqual(response.status_code, 404)


class StudentGradesPageTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="grades-student", password="test-password", role=User.Role.STUDENT
        )
        self.student = Student.objects.create(
            user=self.user, student_number="G1001", first_name="Ada", last_name="Lovelace"
        )
        self.course = Course.objects.create(code="CSE 311", title="Software")
        self.student.enrolled_courses.add(self.course)
        self.midterm = Assessment.objects.create(course=self.course, name="Midterm", weight=40)
        self.midterm_duplicate = Assessment.objects.create(course=self.course, name="Midterm Exam", weight=40)
        self.final = Assessment.objects.create(course=self.course, name="Final Exam", weight=60)
        self.lo = LearningOutcome.objects.create(course=self.course, code="LO1", description="Design software")
        self.po = ProgramOutcome.objects.create(code="PO1", title="Design", description="Design systems")
        AssessmentToLO.objects.create(assessment=self.midterm, learning_outcome=self.lo, weight=100)
        AssessmentToLO.objects.create(assessment=self.final, learning_outcome=self.lo, weight=100)
        LOToPO.objects.create(learning_outcome=self.lo, program_outcome=self.po, weight=100)
        self.client.force_login(self.user)

    def test_bilingual_duplicates_are_deduplicated_and_scores_show_dash_until_complete(self):
        StudentGrade.objects.create(student=self.student, assessment=self.midterm, score=85)

        response = self.client.get(reverse("student_grades"))

        self.assertEqual(response.status_code, 200)
        row = response.context["grade_courses"][0]
        self.assertEqual(len(row["assessments"]), 2)
        self.assertFalse(row["all_assessments_graded"])
        self.assertEqual(row["lo_scores"], {})
        self.assertContains(response, "Midterm")
        self.assertNotContains(response, "Midterm Exam")
        self.assertContains(response, ">-</td>")

    def test_contributions_are_calculated_after_all_unique_assessments_are_graded(self):
        StudentGrade.objects.create(student=self.student, assessment=self.midterm, score=85)
        StudentGrade.objects.create(student=self.student, assessment=self.final, score=95)

        response = self.client.get(reverse("student_grades"))

        row = response.context["grade_courses"][0]
        self.assertTrue(row["all_assessments_graded"])
        self.assertEqual(row["lo_scores"]["LO1"], 90)
        self.assertEqual(row["po_scores"]["PO1"], 90)

    def test_scraped_assessment_weights_supply_lo_scores_when_no_assessment_map_exists(self):
        second_lo = LearningOutcome.objects.create(
            course=self.course, code="LO2", description="Test systems"
        )
        AssessmentToLO.objects.all().delete()
        StudentGrade.objects.create(student=self.student, assessment=self.midterm, score=85)
        StudentGrade.objects.create(student=self.student, assessment=self.final, score=95)

        response = self.client.get(reverse("student_grades"))

        row = response.context["grade_courses"][0]
        self.assertTrue(row["all_assessments_graded"])
        self.assertEqual(row["lo_scores"]["LO1"], 90)
        self.assertEqual(row["lo_scores"]["LO2"], 90)
        self.assertEqual(row["po_scores"]["PO1"], 90)
        for assessment in (self.midterm, self.final):
            mappings = list(AssessmentToLO.objects.filter(assessment=assessment))
            self.assertEqual({m.learning_outcome_id for m in mappings}, {self.lo.pk, second_lo.pk})
            self.assertAlmostEqual(sum(m.weight for m in mappings), 100)


class InstructorAssessmentLOMappingTestCase(TestCase):
    def setUp(self):
        self.instructor = User.objects.create_user(
            username="mapping-instructor", password="test-password", role=User.Role.INSTRUCTOR
        )
        self.course = Course.objects.create(
            code="CSE 411", title="Artificial Intelligence", instructor=self.instructor
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Midterm", weight=100
        )
        self.lo1 = LearningOutcome.objects.create(course=self.course, code="LO1", description="Build models")
        self.lo2 = LearningOutcome.objects.create(course=self.course, code="LO2", description="Evaluate models")
        self.client.force_login(self.instructor)

    def test_instructor_dashboard_displays_equal_split_defaults(self):
        response = self.client.get(reverse("instructor_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assessment-to-LO Weight Matrix")
        mappings = list(AssessmentToLO.objects.filter(assessment=self.assessment))
        self.assertEqual([mapping.weight for mapping in mappings], [50, 50])

    def test_instructor_can_save_valid_row_total_and_trigger_recalculation(self):
        student = Student.objects.create(student_number="M411", first_name="Ada", last_name="Lovelace")
        student.enrolled_courses.add(self.course)
        StudentGrade.objects.create(student=student, assessment=self.assessment, score=80)

        response = self.client.post(
            reverse("save_assessment_lo_mappings"),
            {
                "course_id": self.course.pk,
                f"weight_{self.assessment.pk}_{self.lo1.pk}": "70",
                f"weight_{self.assessment.pk}_{self.lo2.pk}": "30",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(AssessmentToLO.objects.filter(assessment=self.assessment).order_by("learning_outcome__code").values_list("weight", flat=True)),
            [70, 30],
        )
        self.assertIn("LO1", POCalculator.calculate_student_lo_scores(student, self.course))

    def test_instructor_cannot_save_row_that_does_not_total_100(self):
        response = self.client.post(
            reverse("save_assessment_lo_mappings"),
            {
                "course_id": self.course.pk,
                f"weight_{self.assessment.pk}_{self.lo1.pk}": "70",
                f"weight_{self.assessment.pk}_{self.lo2.pk}": "20",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AssessmentToLO.objects.filter(assessment=self.assessment).exists())
        self.assertIn("must total 100%", messages_of(response)[0])


class ScraperCourseCommandTestCase(TestCase):
    SINGLE_RESULT = {
        "success": True,
        "data": {
            "course_code": "CSE 311",
            "course_title": "Software",
            "learning_outcomes": ["Design software"],
            "assessments": [{"name": "Midterm Exam", "weight": 40}, {"name": "Quiz", "weight": 10, "quantity": 2}],
        },
    }

    def run_command(self, *args):
        out = StringIO()
        call_command("scraper_course", OBS_URL, *args, stdout=out)
        return out.getvalue()

    @patch.object(BolognaScraperService, "sync_to_database")
    @patch.object(BolognaScraperService, "scrape_course_data")
    def test_single_course_is_listed_and_synced(self, scrape_course_data, sync_to_database):
        scrape_course_data.return_value = self.SINGLE_RESULT
        sync_to_database.return_value = Course(code="CSE 311", title="Software")

        output = self.run_command("--course-code", "CSE 311")

        scrape_course_data.assert_called_once_with(OBS_URL, course_code="CSE 311")
        self.assertIn("Found Course: CSE 311 - Software", output)
        self.assertIn("  - Design software", output)
        self.assertIn("  - Quiz: contribution 10%, quantity 2", output)
        # Midterm is present, the other standard assessments are reported as missing
        self.assertNotIn("Midterm: not found", output)
        self.assertIn("  - Project: not found", output)
        self.assertIn("  - Final: not found", output)
        self.assertIn("Successfully synced CSE 311 to database!", output)

    @patch.object(BolognaScraperService, "sync_to_database")
    @patch.object(BolognaScraperService, "scrape_course_data")
    def test_batch_result_reports_number_of_courses(self, scrape_course_data, sync_to_database):
        course = self.SINGLE_RESULT["data"]
        scrape_course_data.return_value = {"success": True, "courses": [course, {**course, "course_code": "CSE 312"}]}
        sync_to_database.return_value = [Course(code="CSE 311"), Course(code="CSE 312")]

        output = self.run_command()

        self.assertIn("Found Course: CSE 312 - Software", output)
        self.assertIn("Successfully synced 2 courses to database!", output)

    @patch.object(BolognaScraperService, "sync_to_database")
    @patch.object(BolognaScraperService, "scrape_course_data")
    def test_error_is_printed_and_nothing_is_synced(self, scrape_course_data, sync_to_database):
        scrape_course_data.return_value = {"success": False, "error": "Page not reachable"}

        output = self.run_command()

        self.assertIn("Error: Page not reachable", output)
        sync_to_database.assert_not_called()


class ModelStrTestCase(TestCase):
    def test_models_have_readable_names(self):
        po = ProgramOutcome.objects.create(code="PO1", title="Engineering knowledge", description="-")
        course = Course.objects.create(code="CSE 311", title="Software")
        lo = LearningOutcome.objects.create(course=course, code="LO1", description="-")
        assessment = Assessment.objects.create(course=course, name="Midterm", weight=40.0)
        assessment_to_lo = AssessmentToLO.objects.create(assessment=assessment, learning_outcome=lo, weight=60.0)
        lo_to_po = LOToPO.objects.create(learning_outcome=lo, program_outcome=po, weight=100.0)
        student = Student.objects.create(student_number="1001", first_name="Elif", last_name="Cato")
        grade = StudentGrade.objects.create(student=student, assessment=assessment, score=90.0)

        self.assertEqual(str(po), "PO1 - Engineering knowledge")
        self.assertEqual(str(course), "CSE 311: Software")
        self.assertEqual(str(lo), "CSE 311 - LO1")
        self.assertEqual(str(assessment), "CSE 311 - Midterm (%40.0)")
        self.assertEqual(str(assessment_to_lo), "CSE 311 - Midterm (%40.0) -> LO1 (%60.0)")
        self.assertEqual(str(lo_to_po), "CSE 311 - LO1 -> PO1 (%100.0)")
        self.assertEqual(str(student), "1001 - Elif Cato")
        self.assertEqual(str(grade), "1001 - Elif Cato - Midterm: 90.0")
