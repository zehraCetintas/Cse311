import openpyxl
from django.db import transaction
from main.models import Student, Assessment, StudentGrade


class GradeImporterService:
    @staticmethod
    def import_excel_grades(assessment: Assessment, file_obj):
        """
        Imports student grades from an Excel (.xlsx) file for a specific assessment.
        Expected Excel columns:
        Row 1: Header (Student Number, Score)
        Row 2+: Data (e.g., 202101001, 85.5)
        """
        workbook = openpyxl.load_workbook(file_obj, data_only=True)
        sheet = workbook.active

        grades_to_create = []
        grades_to_update = []
        errors = []

        # Read rows starting from row 2 (skipping header)
        rows = list(sheet.iter_rows(min_row=2, values_only=True))

        if not rows:
            raise ValueError("The uploaded Excel file is empty.")

        # Pre-fetch existing students and grades for query optimization
        student_numbers = [str(row[0]).strip() for row in rows if row[0] is not None]
        students_map = {
            s.student_number: s
            for s in Student.objects.filter(student_number__in=student_numbers)
        }

        existing_grades = {
            g.student_id: g
            for g in StudentGrade.objects.filter(
                assessment=assessment,
                student__student_number__in=student_numbers
            )
        }

        for row_idx, row in enumerate(rows, start=2):
            raw_student_no = row[0]
            raw_score = row[1]

            # Skip empty lines
            if raw_student_no is None and raw_score is None:
                continue

            # 1. Validate Student Number
            if not raw_student_no:
                errors.append(f"Row {row_idx}: Missing student number.")
                continue

            student_no = str(raw_student_no).strip()
            student = students_map.get(student_no)
            if not student:
                errors.append(f"Row {row_idx}: Student with ID '{student_no}' does not exist.")
                continue

            # 2. Validate Score
            try:
                score = float(raw_score)
            except (ValueError, TypeError):
                errors.append(f"Row {row_idx}: Invalid score value '{raw_score}'. Must be a number.")
                continue

            if score < 0.0 or score > 100.0:
                errors.append(f"Row {row_idx}: Score {score} must be between 0 and 100.")
                continue

            # 3. Prepare for Bulk Ingestion
            if student.id in existing_grades:
                grade_record = existing_grades[student.id]
                grade_record.score = score
                grades_to_update.append(grade_record)
            else:
                grades_to_create.append(
                    StudentGrade(
                        student=student,
                        assessment=assessment,
                        score=score
                    )
                )

        # If any validation errors occurred, abort before touching the database
        if errors:
            return {"success": False, "errors": errors, "created": 0, "updated": 0}

        # CSE 321: Atomic transaction ensures data consistency (All-or-Nothing)
        with transaction.atomic():
            if grades_to_create:
                StudentGrade.objects.bulk_create(grades_to_create)
            if grades_to_update:
                StudentGrade.objects.bulk_update(grades_to_update, ['score'])

        return {
            "success": True,
            "errors": [],
            "created": len(grades_to_create),
            "updated": len(grades_to_update)
        }