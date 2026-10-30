from django.contrib.auth import authenticate
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image
from main.models import (
    ProgramOutcome, Course, LearningOutcome, User,
    Assessment, AssessmentToLO, LOToPO, Student, StudentGrade
)
from main.services.calculator import POCalculator


class POCalculatorTestCase(TestCase):
    def setUp(self):
        # 1. POs
        self.po1 = ProgramOutcome.objects.create(code="PO1", title="PO 1", description="Desc 1")
        self.po2 = ProgramOutcome.objects.create(code="PO2", title="PO 2", description="Desc 2")

        # 2. Course
        self.course = Course.objects.create(code="CSE 311", title="Software")

        # 3. LOs
        self.lo1 = LearningOutcome.objects.create(course=self.course, code="LO1", description="LO 1")
        self.lo2 = LearningOutcome.objects.create(course=self.course, code="LO2", description="LO 2")

        # 4. Assessments (Midterm & Project)
        self.midterm = Assessment.objects.create(course=self.course, name="Midterm", weight=60.0)
        self.project = Assessment.objects.create(course=self.course, name="Project", weight=40.0)

        # 5. Assessment -> LO Mappings
        # Midterm -> LO1 60%, LO2 40%
        AssessmentToLO.objects.create(assessment=self.midterm, learning_outcome=self.lo1, weight=60.0)
        AssessmentToLO.objects.create(assessment=self.midterm, learning_outcome=self.lo2, weight=40.0)

        # Project -> LO1 40%, LO2 100%
        AssessmentToLO.objects.create(assessment=self.project, learning_outcome=self.lo1, weight=40.0)
        AssessmentToLO.objects.create(assessment=self.project, learning_outcome=self.lo2, weight=100.0)

        # 6. LO -> PO Mappings
        # LO1 -> PO1 100%
        LOToPO.objects.create(learning_outcome=self.lo1, program_outcome=self.po1, weight=100.0)
        # LO2 -> PO1 50%, PO2 100%
        LOToPO.objects.create(learning_outcome=self.lo2, program_outcome=self.po1, weight=50.0)
        LOToPO.objects.create(learning_outcome=self.lo2, program_outcome=self.po2, weight=100.0)

        # 7. Student: Elif (Midterm=90, Project=80)
        self.student = Student.objects.create(student_number="12345", first_name="Elif", last_name="Cato")
        StudentGrade.objects.create(student=self.student, assessment=self.midterm, score=90.0)
        StudentGrade.objects.create(student=self.student, assessment=self.project, score=80.0)

    def test_slide_worked_example(self):
        # Test LO scores
        lo_scores = POCalculator.calculate_student_lo_scores(self.student, self.course)
        self.assertEqual(lo_scores["LO1"], 86.0)
        self.assertAlmostEqual(lo_scores["LO2"], 82.86, places=1)

        # Test PO scores
        po_scores = POCalculator.calculate_student_po_scores_for_course(self.student, self.course)
        self.assertAlmostEqual(po_scores["PO1"], 85.0, places=1)
        self.assertAlmostEqual(po_scores["PO2"], 82.9, places=1)


class UserRoleTestCase(TestCase):
    def test_superuser_is_saved_and_recognized_as_head_of_faculty(self):
        user = User.objects.create_superuser(
            username="zehra-test",
            email="zehra@example.com",
            password="test-password",
        )

        self.assertEqual(user.role, User.Role.HEAD_OF_FACULTY)
        self.assertTrue(user.is_head())
        self.assertFalse(user.is_instructor())

        user.role = User.Role.INSTRUCTOR
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.HEAD_OF_FACULTY)


from bs4 import BeautifulSoup
from django.test import TestCase
from unittest.mock import Mock, patch
from main.services.bologna_scraper import BolognaScraperService
from main.models import Course, LearningOutcome, Assessment


class BolognaScraperTestCase(TestCase):
    @staticmethod
    def _response(content):
        response = Mock(content=content.encode())
        response.raise_for_status = Mock()
        return response

    @staticmethod
    def _course_detail_html(code, title, outcome, assessments):
        assessment_rows = "".join(
            f"""
            <tr>
                <td data-label="Çalışma">{name}</td>
                <td data-label="Sayısı">1</td>
                <td data-label="Katkı">%<span>{weight}</span></td>
            </tr>
            """
            for name, weight in assessments
        )
        return f"""
        <table id="grdDers">
            <tr><th>Course Unit Code</th><th>Course Unit Title</th></tr>
            <tr><td>{code}</td><td>{title}</td></tr>
        </table>
        <table id="grdOgrenmeCiktilari">
            <tr><th>No</th><th>Learning Outcomes</th></tr>
            <tr>
                <td>1</td>
                <td data-label="Learning Outcomes">{outcome}</td>
            </tr>
        </table>
        <table id="grd_degerlendirme">
            <tr><th>In-Term Studies</th><th>Quantity</th><th>Percentage</th></tr>
            {assessment_rows}
        </table>
        """

    @patch("main.services.bologna_scraper.requests.get")
    def test_detail_url_extracts_and_syncs_course_without_course_code(self, mock_get):
        detail_html = self._course_detail_html(
            "CSE 311",
            "Software",
            "Design secure APIs.",
            [("Midterm", 60), ("Project", 25), ("Final", 15)],
        )
        mock_get.return_value = self._response(detail_html)

        result = BolognaScraperService.scrape_course_data(
            "https://obs.acibadem.edu.tr/oibs/bologna/progCourseDetails.aspx"
            "?curCourse=468678&lang=en"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["course_code"], "CSE311")
        self.assertEqual(result["data"]["course_title"], "Software")
        self.assertEqual(
            result["data"]["assessments"],
            [
                {"name": "Midterm", "weight": 60.0, "quantity": 1},
                {"name": "Project", "weight": 25.0, "quantity": 1},
                {"name": "Final", "weight": 15.0, "quantity": 1},
            ],
        )

        course = BolognaScraperService.sync_to_database(result)
        self.assertEqual(course.learning_outcomes.count(), 1)
        self.assertEqual(
            course.learning_outcomes.get(code="LO1").description,
            "Design secure APIs.",
        )
        self.assertEqual(
            list(course.assessments.order_by("name").values_list("name", "weight")),
            [("Final", 15.0), ("Midterm", 60.0), ("Project", 25.0)],
        )
        mock_get.assert_called_once()

    def test_parser_ignores_assessment_summary_and_total_rows(self):
        html = self._course_detail_html(
            "CSE 311",
            "Software",
            "Design secure APIs.",
            [
                ("Midterm", 30),
                ("Project", 30),
                ("Final", 40),
                ("Total", 100),
                ("Toplam", 100),
                ("Yarıyıl İçi Çalışmaları", 100),
                ("Yıl İçi", 100),
                ("Yarıyıl Sonu Çalışmalarının Katkısı", 100),
            ],
        )

        result = BolognaScraperService.parse_html_content(
            BeautifulSoup(html, "html.parser")
        )

        self.assertEqual(
            result["data"]["assessments"],
            [
                {"name": "Midterm", "weight": 30.0, "quantity": 1},
                {"name": "Project", "weight": 30.0, "quantity": 1},
                {"name": "Final", "weight": 40.0, "quantity": 1},
            ],
        )

    def test_parser_deduplicates_bilingual_assessment_names(self):
        html = self._course_detail_html(
            "CSE 311",
            "Software",
            "Design secure APIs.",
            [
                ("Ara S\u0131nav", 30),
                ("Midterm", 30),
                ("\u00d6dev", 20),
                ("Assignment", 20),
                ("Proje", 50),
                ("Project", 50),
            ],
        )

        result = BolognaScraperService.parse_html_content(
            BeautifulSoup(html, "html.parser")
        )

        self.assertEqual(
            result["data"]["assessments"],
            [
                {"name": "Midterm", "weight": 30.0, "quantity": 1},
                {"name": "Assignment", "weight": 20.0, "quantity": 1},
                {"name": "Project", "weight": 50.0, "quantity": 1},
            ],
        )

    def test_sync_updates_existing_component_assessments_without_accumulating(self):
        scraped_data = {
            "success": True,
            "data": {
                "course_code": "CSE311",
                "course_title": "Software",
                "learning_outcomes": [],
                "assessments": [
                    {"name": "Midterm", "weight": 50},
                    {"name": "Ara S\u0131nav", "weight": 50},
                    {"name": "Final", "weight": 50},
                    {"name": "Final Exam", "weight": 50},
                    {"name": "Total", "weight": 100},
                    {"name": "Y\u0131l \u0130\u00e7i", "weight": 100},
                ],
            },
        }

        course = BolognaScraperService.sync_to_database(scraped_data)
        BolognaScraperService.sync_to_database(scraped_data)

        self.assertEqual(course.assessments.count(), 2)
        self.assertEqual(
            sum(
                assessment.weight
                for assessment in BolognaScraperService.deduplicate_assessments(
                    course.assessments.all()
                )
            ),
            100,
        )

    @patch("main.services.bologna_scraper.requests.get")
    def test_curriculum_url_scrapes_and_syncs_every_course(self, mock_get):
        listing_html = """
        <table>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468678);">CSE 311</a></td>
                <td><span>Software</span></td>
            </tr>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468679);">CSE 312</a></td>
                <td><span>Databases</span></td>
            </tr>
        </table>
        """
        detail_pages = [
            self._course_detail_html(
                "CSE 311",
                "Software",
                "Apply agile software development techniques and create web applications.",
                [("Midterm", 60), ("Project", 40)],
            ),
            self._course_detail_html(
                "CSE 312",
                "Databases",
                "Design relational databases and write queries for applications.",
                [("Midterm", 50), ("Final", 50)],
            ),
        ]
        mock_get.side_effect = [
            self._response("<html>Program page</html>"),
            self._response(listing_html),
            *(self._response(page) for page in detail_pages),
        ]

        result = BolognaScraperService.scrape_course_data(
            "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx"
            "?lang=en&curOp=showPac&curUnit=14&curSunit=6246"
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            [(course["course_code"], course["course_title"]) for course in result["courses"]],
            [("CSE311", "Software"), ("CSE312", "Databases")],
        )
        courses = BolognaScraperService.sync_to_database(result)
        self.assertEqual(len(courses), 2)
        self.assertEqual(Course.objects.count(), 2)
        self.assertEqual(
            courses[0].learning_outcomes.get(code="LO1").description,
            "Apply agile software development techniques and create web applications.",
        )
        self.assertEqual(
            list(courses[1].assessments.order_by("name").values_list("name", "weight")),
            [("Final", 50.0), ("Midterm", 50.0)],
        )
        self.assertEqual(mock_get.call_count, 4)

    def test_single_course_scraping_rejects_excluded_prefixes(self):
        mock_get = Mock()
        mock_get.return_value = self._response(
            self._course_detail_html(
                "MED 101", "Medicine elective", "General studies.", []
            )
        )

        with patch("main.services.bologna_scraper.requests.get", mock_get):
            result = BolognaScraperService.scrape_course_data(
                "https://obs.acibadem.edu.tr/course.aspx"
            )

        self.assertFalse(result["success"])
        self.assertIn("ACU, MED, or EMED", result["error"])
        self.assertFalse(Course.objects.exists())

    def test_single_course_scraping_keeps_codes_with_acu_elsewhere(self):
        mock_get = Mock()
        mock_get.return_value = self._response(
            self._course_detail_html(
                "CSEACU 101", "ACU Studies", "Study applications.", []
            )
        )

        with patch("main.services.bologna_scraper.requests.get", mock_get):
            result = BolognaScraperService.scrape_course_data(
                "https://obs.acibadem.edu.tr/course.aspx"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["course_code"], "CSEACU101")

    def test_single_course_scraping_recognizes_ads_course_codes(self):
        response = self._response(
            self._course_detail_html(
                "ADS 1001", "Applied Data Science", "Analyze data sets.", []
            )
        )

        with patch(
            "main.services.bologna_scraper.requests.get",
            return_value=response,
        ):
            result = BolognaScraperService.scrape_course_data(
                "https://obs.acibadem.edu.tr/course.aspx"
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["course_code"], "ADS1001")

    @patch("main.services.bologna_scraper.requests.get")
    def test_catalog_scraping_excludes_unwanted_prefixes_and_keeps_ads(
        self, mock_get
    ):
        listing_html = """
        <table>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468600);">ACU 101</a></td>
                <td>University Common Elective</td>
            </tr>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468677);">MED 101</a></td>
                <td>Medicine</td>
            </tr>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468678);">CSE 311</a></td>
                <td>Software</td>
            </tr>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468679);">ADS 1001</a></td>
                <td>Applied Data Science</td>
            </tr>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468680);">EMED 101</a></td>
                <td>Emergency Medicine</td>
            </tr>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468681);">CSEACU 101</a></td>
                <td>ACU Studies</td>
            </tr>
        </table>
        """
        ordinary_detail = self._course_detail_html(
            "CSE 311", "Software", "Design applications.", [("Final", 100)]
        )
        ads_detail = self._course_detail_html(
            "ADS 1001", "Applied Data Science", "Analyze data sets.", [("Final", 100)]
        )
        internal_acu_detail = self._course_detail_html(
            "CSEACU 101", "ACU Studies", "Study applications.", [("Final", 100)]
        )
        mock_get.side_effect = [
            self._response("<html>Program page</html>"),
            self._response(listing_html),
            self._response(ordinary_detail),
            self._response(ads_detail),
            self._response(internal_acu_detail),
        ]

        result = BolognaScraperService.scrape_course_data(
            "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx"
            "?lang=en&curOp=showPac&curUnit=14&curSunit=6246"
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            [course["course_code"] for course in result["courses"]],
            ["CSE311", "ADS1001", "CSEACU101"],
        )
        self.assertEqual(mock_get.call_count, 5)
        synced_courses = BolognaScraperService.sync_to_database(result)
        self.assertEqual(
            [course.code for course in synced_courses],
            ["CSE311", "ADS1001", "CSEACU101"],
        )
        self.assertFalse(
            any(
                course.code.upper().startswith(("ACU", "MED", "EMED"))
                for course in Course.objects.all()
            )
        )

    @patch("main.services.bologna_scraper.requests.get")
    def test_program_url_selects_course_and_parses_contributions(self, mock_get):
        program_listing = """
        <table>
            <tr>
                <td><a onclick="return prolizOpenCourseDetails(468678);">CSE 311</a></td>
                <td>Software</td>
            </tr>
        </table>
        """
        course_details = """
        <table id="grdDers">
            <tr>
                <th>Semester</th><th>Course Unit Code</th>
                <th>Course Unit Title</th>
            </tr>
            <tr><td>5</td><td>CSE 311</td><td>Software</td></tr>
        </table>
        <table id="grd_degerlendirme">
            <tr><th>In-Term Studies</th><th>Quantity</th><th>Percentage</th></tr>
            <tr>
                <td data-label="Çalışma">Midterm</td>
                <td data-label="Sayısı">5</td>
                <td data-label="Katkı">%<span>75</span></td>
            </tr>
            <tr>
                <td data-label="Çalışma">Project</td>
                <td data-label="Sayısı">1</td>
                <td data-label="Katkı">%<span>25</span></td>
            </tr>
            <tr><td>Total</td><td></td><td>100</td></tr>
        </table>
        <table id="grd_workload">
            <tr><th>Work Load</th><th>Quantity</th><th>Percentage</th></tr>
            <tr>
                <td data-label="Çalışma">Course Duration</td>
                <td data-label="Sayısı">14</td>
                <td data-label="Katkı">42</td>
            </tr>
        </table>
        """
        responses = [
            Mock(content=b"<html></html>"),
            Mock(content=program_listing.encode()),
            Mock(content=course_details.encode()),
        ]
        for response in responses:
            response.raise_for_status = Mock()
        mock_get.side_effect = responses

        result = BolognaScraperService.scrape_course_data(
            "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx"
            "?lang=en&curOp=showPac&curUnit=14&curSunit=6246",
            course_code="CSE 311",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["course_code"], "CSE311")
        self.assertEqual(result["data"]["course_title"], "Software")
        self.assertEqual(
            result["data"]["assessments"],
            [
                {"name": "Midterm", "weight": 75.0, "quantity": 5},
                {"name": "Project", "weight": 25.0, "quantity": 1},
            ],
        )
        self.assertEqual(mock_get.call_count, 3)

    def test_html_parsing_and_db_sync(self):
        # Sample HTML mimicking the university syllabus structure
        mock_html = """
        <html>
            <head><title>CSE 311 Software</title></head>
            <body>
                <table>
                    <tr><td>Code</td><td>CSE 311</td></tr>
                    <tr><td>Course Title</td><td>Software</td></tr>
                </table>
                <table>
                    <tr><th>Learning Outcomes</th></tr>
                    <tr><td>1. Learn design choices and philosophy behind SD.</td></tr>
                    <tr><td>2. Apply agile SD methodology and best practices.</td></tr>
                </table>
                <table>
                    <tr><th>Assessment Components</th><th>Weight</th></tr>
                    <tr><td>Midterm I</td><td>25%</td></tr>
                    <tr><td>Midterm II</td><td>25%</td></tr>
                    <tr><td>Project (Demo)</td><td>40%</td></tr>
                    <tr><td>Total</td><td>100%</td></tr>
                </table>
            </body>
        </html>
        """
        soup = BeautifulSoup(mock_html, "html.parser")
        parsed_result = BolognaScraperService.parse_html_content(soup)

        self.assertTrue(parsed_result["success"])
        self.assertEqual(parsed_result["data"]["course_code"], "CSE311")
        self.assertEqual(len(parsed_result["data"]["learning_outcomes"]), 2)
        self.assertEqual(len(parsed_result["data"]["assessments"]), 3)

        # Test database sync
        course = BolognaScraperService.sync_to_database(parsed_result)
        self.assertEqual(Course.objects.filter(code="CSE311").count(), 1)
        self.assertEqual(course.learning_outcomes.count(), 2)
        self.assertEqual(course.assessments.count(), 3)
import openpyxl
from io import BytesIO
from django.test import TestCase
from main.models import Course, Assessment, Student, StudentGrade
from main.services.grade_importer import GradeImporterService


class GradeImporterTestCase(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="CSE 311", title="Software")
        self.midterm = Assessment.objects.create(course=self.course, name="Midterm", weight=40.0)

        # Create two sample students
        self.student1 = Student.objects.create(student_number="S101", first_name="Ali", last_name="Yılmaz")
        self.student2 = Student.objects.create(student_number="S102", first_name="Ayşe", last_name="Demir")

    def create_excel_in_memory(self, rows, header=("Student Number", "Score")):
        """Helper function to create an Excel file directly in memory."""
        wb = openpyxl.Workbook()
        ws = wb.active
        if header is not None:
            ws.append(header)
        for r in rows:
            ws.append(r)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    def test_successful_bulk_import(self):
        # Prepare valid Excel data
        excel_file = self.create_excel_in_memory([
            ["S101", 85.0],
            ["S102", 92.5],
        ])

        result = GradeImporterService.import_excel_grades(self.midterm, excel_file)
        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 2)

        # Verify records in the database
        grade1 = StudentGrade.objects.get(student=self.student1, assessment=self.midterm)
        self.assertEqual(grade1.score, 85.0)

    def test_import_validation_error_rollback(self):
        # Invalid rows after a metadata row and a dynamically detected header.
        excel_file = self.create_excel_in_memory([
            ["cse311 midterm"],
            ["Student Number", "Grade"],
            ["S101", 70.0],
            ["S102", 80.0],
            ["S101", 150.0],
        ], header=None)

        result = GradeImporterService.import_excel_grades(self.midterm, excel_file)
        self.assertFalse(result["success"])
        self.assertIn("Row 5: Score 150.0 must be between 0 and 100.", result["errors"])

        # Verify nothing was saved (Atomic Rollback)
        self.assertEqual(StudentGrade.objects.filter(assessment=self.midterm).count(), 0)

    def test_import_detects_headers_below_metadata_and_maps_columns(self):
        excel_file = self.create_excel_in_memory(
            [
                ["cse311 midterm"],
                ["Student ID", "Student Name", "Grade"],
                ["S101", "Ali Yılmaz", 85.0],
                ["S102", "Ayşe Demir", 92.5],
            ],
            header=None,
        )

        result = GradeImporterService.import_excel_grades(self.midterm, excel_file)

        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 2)
        self.assertEqual(
            StudentGrade.objects.get(
                student=self.student1, assessment=self.midterm
            ).score,
            85.0,
        )
        self.assertEqual(
            StudentGrade.objects.get(
                student=self.student2, assessment=self.midterm
            ).score,
            92.5,
        )

    def test_unknown_student_rejects_entire_import(self):
        excel_file = self.create_excel_in_memory(
            [
                ["Student Number", "Score"],
                ["S101", 70.0],
                ["UNKNOWN", 88.0],
            ],
            header=None,
        )

        result = GradeImporterService.import_excel_grades(self.midterm, excel_file)

        self.assertFalse(result["success"])
        self.assertIn(
            "Row 3: Student with ID 'UNKNOWN' does not exist in the database.",
            result["errors"],
        )
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(StudentGrade.objects.filter(assessment=self.midterm).count(), 0)


from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse


class InstructorDashboardViewTestCase(TestCase):
    def setUp(self):
        self.instructor = User.objects.create_user(
            username="instructor",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        self.course = Course.objects.create(
            code="CSE 311", title="Software Engineering", instructor=self.instructor
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Midterm", weight=40
        )
        self.other_instructor = User.objects.create_user(
            username="other-instructor",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        self.other_course = Course.objects.create(
            code="CSE 312", title="Databases", instructor=self.other_instructor
        )

    def test_dashboard_defaults_to_first_assigned_course_only(self):
        self.client.force_login(self.instructor)

        response = self.client.get(reverse("instructor_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_course"], self.course)
        self.assertEqual(list(response.context["courses"]), [self.course])
        self.assertContains(response, "Assessment total: 40.00%")

    def test_dashboard_redirects_anonymous_users_to_login(self):
        response = self.client.get(reverse("instructor_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/?next=/instructor/")

    def test_dashboard_forbids_users_without_an_allowed_role(self):
        student = User.objects.create_user(
            username="student",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.client.force_login(student)

        response = self.client.get(reverse("instructor_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_head_of_faculty_cannot_access_instructor_workspace(self):
        head = User.objects.create_user(
            username="faculty-head",
            password="test-password",
            role=User.Role.HEAD_OF_FACULTY,
        )
        self.client.force_login(head)

        response = self.client.get(reverse("instructor_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_instructor_dashboard_and_selection_only_include_assigned_courses(self):
        self.client.force_login(self.instructor)

        response = self.client.get(
            reverse("instructor_dashboard"),
            {"course_id": self.other_course.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["courses"]), [self.course])
        self.assertEqual(response.context["selected_course"], self.course)
        self.assertNotContains(response, self.other_course.code)

    def test_instructor_cannot_assign_courses_or_import_bologna_courses(self):
        self.client.force_login(self.instructor)

        assignment_response = self.client.post(
            reverse("assign_course_instructor"),
            {
                "course_id": self.other_course.pk,
                "instructor_id": self.instructor.pk,
            },
        )
        import_response = self.client.post(
            reverse("import_bologna_course"),
            {"syllabus_url": "https://obs.acibadem.edu.tr/course.aspx"},
        )

        self.assertEqual(assignment_response.status_code, 403)
        self.assertEqual(import_response.status_code, 403)
        self.other_course.refresh_from_db()
        self.assertEqual(self.other_course.instructor, self.other_instructor)

    @staticmethod
    def _excel_upload(rows):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Student Number", "Score"])
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return SimpleUploadedFile(
            "grades.xlsx",
            output.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

    def test_grade_upload_imports_grades_for_assigned_assessment(self):
        student = Student.objects.create(
            student_number="S311", first_name="Ada", last_name="Lovelace"
        )
        self.client.force_login(self.instructor)

        response = self.client.post(
            reverse("upload_grades"),
            {
                "course_id": self.course.pk,
                "assessment_id": self.assessment.pk,
                "grades_file": self._excel_upload([["S311", 87.5]]),
            },
            follow=True,
        )

        self.assertEqual(
            response.redirect_chain,
            [(f"{reverse('instructor_dashboard')}?course_id={self.course.pk}", 302)],
        )
        self.assertEqual(
            StudentGrade.objects.get(
                student=student, assessment=self.assessment
            ).score,
            87.5,
        )
        self.assertContains(response, "1 created, 0 updated")

    def test_grade_upload_rejects_assessment_from_another_instructor(self):
        foreign_assessment = Assessment.objects.create(
            course=self.other_course, name="Final", weight=100
        )
        self.client.force_login(self.instructor)

        response = self.client.post(
            reverse("upload_grades"),
            {
                "assessment_id": foreign_assessment.pk,
                "grades_file": self._excel_upload([["S311", 87.5]]),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            StudentGrade.objects.filter(assessment=foreign_assessment).exists()
        )

    @patch("main.views.BolognaScraperService.scrape_course_data")
    def test_head_imports_bologna_course_unassigned_for_workspace_assignment(
        self, scrape_course_data
    ):
        scraped_result = {
            "success": True,
            "error": None,
            "data": {
                "course_code": "CSE313",
                "course_title": "Algorithms",
                "learning_outcomes": [],
                "assessments": [],
            },
        }
        scrape_course_data.return_value = scraped_result
        head = User.objects.create_user(
            username="bologna-import-head",
            password="test-password",
            role=User.Role.HEAD_OF_FACULTY,
        )
        self.client.force_login(head)

        response = self.client.post(
            reverse("import_bologna_course"),
            {
                "syllabus_url": "https://obs.acibadem.edu.tr/course.aspx",
                "course_id": self.course.pk,
            },
            follow=True,
        )

        scrape_course_data.assert_called_once_with(
            "https://obs.acibadem.edu.tr/course.aspx"
        )
        self.assertEqual(
            response.redirect_chain,
            [(reverse("head_dashboard"), 302)],
        )
        imported_course = Course.objects.get(code="CSE313")
        imported_course.refresh_from_db()
        self.assertIsNone(imported_course.instructor)
        self.assertEqual(
            imported_course.syllabus_url,
            "https://obs.acibadem.edu.tr/course.aspx",
        )
        self.assertContains(response, "Imported CSE313")


class StudentDashboardViewTestCase(TestCase):
    def setUp(self):
        self.student_user = User.objects.create_user(
            username="student-dashboard-user",
            password="test-password",
            role=User.Role.STUDENT,
        )
        self.student = Student.objects.create(
            student_number="S311-01",
            first_name="Ada",
            last_name="Lovelace",
            faculty="Faculty of Engineering / Mühendislik Fakültesi",
            department="Computer Engineering / Bilgisayar Mühendisliği",
            user=self.student_user,
        )
        self.course = Course.objects.create(
            code="CSE 311", title="Software Engineering"
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Midterm", weight=100
        )
        self.learning_outcome = LearningOutcome.objects.create(
            course=self.course, code="LO1", description="Design software systems."
        )
        self.student.enrolled_courses.add(self.course)
        AssessmentToLO.objects.create(
            assessment=self.assessment,
            learning_outcome=self.learning_outcome,
            weight=100,
        )
        self.program_outcomes = [
            ProgramOutcome.objects.create(
                code=f"PO{number}",
                title=f"Program Outcome {number}",
                description=f"Outcome {number}",
            )
            for number in range(1, 12)
        ]
        LOToPO.objects.create(
            learning_outcome=self.learning_outcome,
            program_outcome=self.program_outcomes[0],
            weight=100,
        )
        StudentGrade.objects.create(
            student=self.student, assessment=self.assessment, score=80
        )

    def test_student_can_access_dashboard_for_linked_profile(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse("student_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["student"], self.student)
        self.assertContains(response, "Ada Lovelace")
        self.assertContains(response, "Faculty of Engineering")
        self.assertContains(response, "Computer Engineering")
        self.assertEqual(response.context["full_name"], "Ada Lovelace")
        self.assertEqual(response.context["enrolled_courses"], [self.course])
        self.assertEqual(
            list(response.context["learning_outcomes"]),
            [self.learning_outcome],
        )
        self.assertContains(response, "Midterm")

    def test_student_can_upload_a_profile_picture(self):
        image_buffer = BytesIO()
        Image.new("RGB", (1, 1), color="blue").save(image_buffer, format="PNG")

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.force_login(self.student_user)
                response = self.client.post(
                    reverse("update_student_profile_picture"),
                    {
                        "profile_picture": SimpleUploadedFile(
                            "avatar.png",
                            image_buffer.getvalue(),
                            content_type="image/png",
                        )
                    },
                )

                self.assertRedirects(response, reverse("student_dashboard"))
                self.student.refresh_from_db()
                self.assertTrue(self.student.profile_picture.name.startswith("profile_pics/"))
                self.assertTrue(self.student.profile_picture.storage.exists(
                    self.student.profile_picture.name
                ))
                self.assertTrue(
                    self.student.profile_picture.url.startswith("/media/")
                )

    def test_instructor_can_upload_a_profile_picture(self):
        instructor = User.objects.create_user(
            username="dashboard-picture-instructor",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        image_buffer = BytesIO()
        Image.new("RGB", (1, 1), color="green").save(image_buffer, format="PNG")

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.force_login(instructor)
                response = self.client.post(
                    reverse("update_profile_picture"),
                    {
                        "profile_picture": SimpleUploadedFile(
                            "avatar.png",
                            image_buffer.getvalue(),
                            content_type="image/png",
                        )
                    },
                )

                self.assertRedirects(response, reverse("instructor_dashboard"))
                instructor.refresh_from_db()
                self.assertTrue(instructor.profile_picture.name.startswith("profile_pics/"))
                self.assertTrue(
                    instructor.profile_picture.storage.exists(
                        instructor.profile_picture.name
                    )
                )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("student_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/?next=/student/")

    def test_radar_context_contains_all_outcomes_and_calculated_scores(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse("student_dashboard"))

        self.assertEqual(
            response.context["po_labels"],
            [f"PO{number}" for number in range(1, 12)],
        )
        self.assertEqual(response.context["po_scores"][0], 80.0)
        self.assertEqual(response.context["po_scores"][1:], [None] * 10)
        self.assertContains(response, "po-radar-chart")

    def test_program_outcomes_are_shown_on_the_separate_po_list_page(self):
        self.client.force_login(self.student_user)

        response = self.client.get(reverse("student_program_outcomes"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "student/program_outcomes.html")
        self.assertContains(response, "PO List")
        self.assertContains(response, "Program Outcome 1")
        self.assertContains(
            response,
            f'href="{reverse("student_dashboard")}#learning-outcomes"',
        )
        self.assertContains(
            response,
            f'href="{reverse("student_dashboard")}#academic-breakdown"',
        )
        dashboard_response = self.client.get(reverse("student_dashboard"))
        self.assertNotContains(dashboard_response, "Outcome 1")

    def test_non_student_cannot_access_program_outcomes_page(self):
        instructor = User.objects.create_user(
            username="po-list-instructor",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        self.client.force_login(instructor)

        response = self.client.get(reverse("student_program_outcomes"))

        self.assertEqual(response.status_code, 403)


class HeadDashboardViewTestCase(TestCase):
    def setUp(self):
        self.head = User.objects.create_user(
            username="department-head",
            password="test-password",
            role=User.Role.HEAD_OF_FACULTY,
        )
        self.instructor = User.objects.create_user(
            username="department-instructor",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        self.course = Course.objects.create(
            code="CSE 311",
            title="Software Engineering",
            instructor=self.instructor,
        )
        self.assessment = Assessment.objects.create(
            course=self.course, name="Final", weight=100
        )
        self.outcome = LearningOutcome.objects.create(
            course=self.course, code="LO1", description="Design software."
        )
        AssessmentToLO.objects.create(
            assessment=self.assessment, learning_outcome=self.outcome, weight=100
        )
        self.program_outcomes = [
            ProgramOutcome.objects.create(
                code=f"PO{number}",
                title=f"Program Outcome {number}",
                description=f"Outcome {number}",
            )
            for number in range(1, 12)
        ]
        LOToPO.objects.create(
            learning_outcome=self.outcome,
            program_outcome=self.program_outcomes[0],
            weight=100,
        )
        self.students = [
            Student.objects.create(
                student_number=f"STU-{number}",
                first_name=f"Student{number}",
                last_name="Example",
            )
            for number in range(2)
        ]
        StudentGrade.objects.create(
            student=self.students[0], assessment=self.assessment, score=60
        )
        StudentGrade.objects.create(
            student=self.students[1], assessment=self.assessment, score=100
        )

    def test_head_of_faculty_can_access_dashboard(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "faculty_head/dashboard.html")

    def test_dashboard_hides_existing_acu_prefixed_courses_from_assignment_workspace(self):
        excluded_course = Course.objects.create(
            code="ACU101",
            title="University Common Elective",
        )
        self.client.force_login(self.head)

        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_courses"], 1)
        self.assertEqual(
            [item["course"].pk for item in response.context["course_audit"]],
            [self.course.pk],
        )
        self.assertNotContains(response, "ACU101")
        self.assertTrue(Course.objects.filter(pk=excluded_course.pk).exists())

    def test_instructor_and_student_are_forbidden(self):
        student_user = User.objects.create_user(
            username="ordinary-student",
            password="test-password",
            role=User.Role.STUDENT,
        )
        for user in (self.instructor, student_user):
            with self.subTest(role=user.role):
                self.client.force_login(user)

                response = self.client.get(reverse("head_dashboard"))

                self.assertEqual(response.status_code, 403)

    def test_dashboard_aggregates_metrics_and_department_po_averages(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_courses"], 1)
        self.assertEqual(response.context["total_instructors"], 1)
        self.assertEqual(response.context["total_students"], 2)
        self.assertEqual(response.context["po_averages"][0], 80.0)
        self.assertEqual(response.context["po_averages"][1:], [None] * 10)
        self.assertEqual(
            response.context["course_audit"][0]["student_count"], 2
        )
        self.assertTrue(
            response.context["course_audit"][0]["assessment_weight_is_valid"]
        )

    def test_dashboard_total_weight_ignores_legacy_summary_assessments(self):
        self.assessment.weight = 40
        self.assessment.save(update_fields=["weight"])
        for assessment_name in (
            "Total",
            "Yar\u0131y\u0131l \u0130\u00e7i \u00c7al\u0131\u015fmalar\u0131",
            "Y\u0131l \u0130\u00e7i",
            "Yar\u0131y\u0131l Sonu \u00c7al\u0131\u015fmalar\u0131n\u0131n Katk\u0131s\u0131",
        ):
            Assessment.objects.create(
                course=self.course,
                name=assessment_name,
                weight=100,
            )
        Assessment.objects.create(course=self.course, name="Final Exam", weight=40)
        Assessment.objects.create(course=self.course, name="Midterm", weight=30)
        Assessment.objects.create(
            course=self.course, name="Ara S\u0131nav", weight=30
        )
        Assessment.objects.create(course=self.course, name="Project", weight=30)
        Assessment.objects.create(course=self.course, name="Proje", weight=30)
        self.client.force_login(self.head)

        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(
            response.context["course_audit"][0]["assessment_total_weight"],
            100,
        )
        self.assertEqual(
            response.context["course_audit"][0]["status"],
            "Compliant",
        )
        self.assertContains(response, "100.00%")
        self.assertNotContains(response, "300.00%")

    def test_dashboard_renders_accreditation_warning_for_low_po_average(self):
        StudentGrade.objects.filter(student=self.students[0]).update(score=20)
        StudentGrade.objects.filter(student=self.students[1]).update(score=40)
        self.client.force_login(self.head)

        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(response.context["po_averages"][0], 30.0)
        self.assertEqual(len(response.context["po_warnings"]), 1)
        self.assertEqual(response.context["po_warnings"][0]["label"], "PO1")
        self.assertContains(response, "Accreditation Warning")
        self.assertContains(response, "PO1 · Program Outcome 1")
        self.assertContains(response, "Outcome 1")
        self.assertContains(response, "30.00%")

    def test_head_can_assign_multiple_courses_to_one_instructor(self):
        second_course = Course.objects.create(
            code="CSE 312", title="Databases"
        )
        self.client.force_login(self.head)

        for course in (self.course, second_course):
            with self.subTest(course=course.code):
                response = self.client.post(
                    reverse("assign_course_instructor"),
                    {
                        "course_id": course.pk,
                        "instructor_id": self.instructor.pk,
                    },
                )
                self.assertRedirects(response, reverse("head_dashboard"))

        self.assertEqual(
            list(
                self.instructor.assigned_courses.order_by("code").values_list(
                    "code", flat=True
                )
            ),
            ["CSE 311", "CSE 312"],
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/?next=/faculty-head/")


class AuthenticationViewTestCase(TestCase):
    def setUp(self):
        self.reset_user = User.objects.create_user(
            username="987654321",
            password="old-password",
            email="reset.student@example.edu",
            first_name="Reset",
            last_name="Student",
            role=User.Role.STUDENT,
        )

    @staticmethod
    def _captcha_answer(client):
        return client.session["captcha_result"]

    def _login_as(self, user):
        self.client.get(reverse("login"))
        response = self.client.post(
            reverse("login"),
            {
                "number": user.username,
                "password": "test-password",
                "captcha_answer": self._captcha_answer(self.client),
            },
        )
        return response

    def test_reset_password_page_displays_email_verification_workflow(self):
        response = self.client.get(reverse("reset_password"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "9-digit ID Number")
        self.assertContains(response, "Registered email")
        self.assertContains(response, "Confirm new password")

    def test_password_reset_accepts_valid_id_email_and_password(self):
        response = self.client.post(
            reverse("reset_password"),
            {
                "number": self.reset_user.username,
                "email": self.reset_user.email.upper(),
                "new_password": "SecurePass123",
                "confirm_password": "SecurePass123",
            },
            follow=True,
        )

        self.reset_user.refresh_from_db()
        self.assertRedirects(response, reverse("login"))
        self.assertTrue(self.reset_user.check_password("SecurePass123"))
        self.assertContains(
            response,
            "Your password has been successfully updated. You can now log in with your new password.",
        )

    def test_password_reset_rejects_short_non_alphanumeric_and_mismatched_passwords(
        self,
    ):
        invalid_passwords = (
            ("Short1", "Short1"),
            ("LettersOnly", "LettersOnly"),
            ("12345678", "12345678"),
            ("SecurePass123", "DifferentPass123"),
        )
        for new_password, confirm_password in invalid_passwords:
            with self.subTest(new_password=new_password):
                response = self.client.post(
                    reverse("reset_password"),
                    {
                        "number": self.reset_user.username,
                        "email": self.reset_user.email,
                        "new_password": new_password,
                        "confirm_password": confirm_password,
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["active_tab"], "reset")
                self.assertTrue(response.context["reset_errors"])
                self.reset_user.refresh_from_db()
                self.assertTrue(self.reset_user.check_password("old-password"))

    def test_password_reset_rejects_id_and_email_that_do_not_match(self):
        response = self.client.post(
            reverse("reset_password"),
            {
                "number": self.reset_user.username,
                "email": "wrong@example.edu",
                "new_password": "SecurePass123",
                "confirm_password": "SecurePass123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "No active account found with the provided ID number and email combination.",
        )
        self.reset_user.refresh_from_db()
        self.assertTrue(self.reset_user.check_password("old-password"))

    def test_login_redirects_each_role_to_its_dashboard(self):
        instructor = User.objects.create_user(
            username="instructor-login",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        head = User.objects.create_user(
            username="faculty-login",
            password="test-password",
            role=User.Role.HEAD_OF_FACULTY,
        )
        student_user = User.objects.create_user(
            username="123456789",
            password="test-password",
            role=User.Role.STUDENT,
        )
        Student.objects.create(
            user=student_user,
            student_number=student_user.username,
            first_name="Student",
            last_name="Login",
        )

        for user, dashboard_name in (
            (instructor, "instructor_dashboard"),
            (head, "head_dashboard"),
            (student_user, "student_dashboard"),
        ):
            with self.subTest(role=user.role):
                response = self._login_as(user)

                self.assertRedirects(response, reverse(dashboard_name))
                self.client.logout()

    def test_login_rejects_incorrect_captcha(self):
        user = User.objects.create_user(
            username="captcha-user",
            password="test-password",
            role=User.Role.INSTRUCTOR,
        )
        self.client.get(reverse("login"))
        correct_answer = self._captcha_answer(self.client)

        response = self.client.post(
            reverse("login"),
            {
                "number": user.username,
                "password": "test-password",
                "captcha_answer": correct_answer + 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "math verification answer is incorrect")

    @patch("main.views.random.randint", return_value=123456789)
    def test_student_registration_creates_number_profile_and_secure_password(
        self, mocked_number
    ):
        response = self.client.post(
            reverse("register_student"),
            {
                "first_name": "Grace",
                "last_name": "Hopper",
                "email": "grace@example.edu",
            },
            follow=True,
        )

        user = User.objects.get(username="123456789")
        student = Student.objects.get(user=user)
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertTrue(user.is_active)
        self.assertEqual(student.student_number, "123456789")
        self.assertEqual((student.first_name, student.last_name), ("Grace", "Hopper"))
        self.assertRegex(student.student_number, r"^[1-9]\d{8}$")
        self.assertContains(response, "Registration Complete!")
        credential_message = next(
            message
            for message in response.context["messages"]
            if "Registration Complete!" in str(message)
        )
        temporary_password = str(credential_message).split(
            "Temporary Password: ", 1
        )[1].split(". Please note it!", 1)[0]
        self.assertTrue(user.check_password(temporary_password))
        authenticated_user = authenticate(
            username=user.username, password=temporary_password
        )
        self.assertEqual(authenticated_user, user)
        self.assertGreaterEqual(len(temporary_password), 8)
        self.assertLessEqual(len(temporary_password), 10)
        self.assertRegex(temporary_password, r"[A-Z]")
        self.assertRegex(temporary_password, r"[a-z]")
        self.assertRegex(temporary_password, r"\d")
        self.assertRegex(temporary_password, r"^[A-Za-z0-9]+$")

        self.client.get(reverse("login"))
        response = self.client.post(
            reverse("login"),
            {
                "number": user.username,
                "password": temporary_password,
                "captcha_answer": self.client.session["captcha_result"],
            },
        )
        self.assertRedirects(response, reverse("student_dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        mocked_number.assert_called_once()

    @patch("main.views.random.randint", return_value=234567891)
    def test_instructor_registration_creates_active_login_account(
        self, mocked_number
    ):
        response = self.client.post(
            reverse("register_student"),
            {
                "role": User.Role.INSTRUCTOR,
                "first_name": "Deniz",
                "last_name": "Yılmaz",
                "email": "deniz.yilmaz@university.edu",
            },
            follow=True,
        )

        user = User.objects.get(username="234567891")
        self.assertEqual(user.role, User.Role.INSTRUCTOR)
        self.assertTrue(user.is_active)
        self.assertEqual(user.first_name, "Deniz")
        self.assertEqual(user.last_name, "Yılmaz")
        self.assertFalse(Student.objects.filter(student_number=user.username).exists())
        self.assertContains(response, "Instructor Registration Successful!")
        credential_message = next(
            message
            for message in response.context["messages"]
            if "Instructor Registration Successful!" in str(message)
        )
        temporary_password = str(credential_message).split(
            "Temporary Password: ", 1
        )[1].rstrip(".")
        self.assertRegex(user.username, r"^[1-9]\d{8}$")
        self.assertGreaterEqual(len(temporary_password), 8)
        self.assertLessEqual(len(temporary_password), 10)
        self.assertRegex(temporary_password, r"[A-Z]")
        self.assertRegex(temporary_password, r"[a-z]")
        self.assertRegex(temporary_password, r"\d")
        self.assertRegex(temporary_password, r"^[A-Za-z0-9]+$")
        self.assertEqual(
            authenticate(username=user.username, password=temporary_password),
            user,
        )
        mocked_number.assert_called_once()

        self.client.get(reverse("login"))
        login_response = self.client.post(
            reverse("login"),
            {
                "number": user.username,
                "password": temporary_password,
                "captcha_answer": self.client.session["captcha_result"],
            },
        )
        self.assertRedirects(login_response, reverse("instructor_dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
