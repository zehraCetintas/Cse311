from django.test import TestCase
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
