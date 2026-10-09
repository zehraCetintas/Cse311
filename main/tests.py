from django.test import TestCase
from main.models import (
    ProgramOutcome, Course, LearningOutcome,
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

    def create_excel_in_memory(self, rows):
        """Helper function to create an Excel file directly in memory."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Student Number", "Score"])  # Header
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
        # Prepare Excel with an invalid score (>100)
        excel_file = self.create_excel_in_memory([
            ["S101", 70.0],
            ["S102", 150.0],  # Invalid score
        ])

        result = GradeImporterService.import_excel_grades(self.midterm, excel_file)
        self.assertFalse(result["success"])
        self.assertIn("must be between 0 and 100", result["errors"][0])

        # Verify nothing was saved (Atomic Rollback)
        self.assertEqual(StudentGrade.objects.filter(assessment=self.midterm).count(), 0)
