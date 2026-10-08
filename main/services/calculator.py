from main.models import Student, Course, ProgramOutcome, LearningOutcome, AssessmentToLO, LOToPO, StudentGrade

class POCalculator:
    @staticmethod
    def calculate_student_lo_scores(student: Student, course: Course):
        """
        Calculates LO scores for a student in a specific course.
        LO Score = Sum(Assessment Score * Weight) / Sum(Weights)
        """
        lo_scores = {}
        learning_outcomes = course.learning_outcomes.all()

        for lo in learning_outcomes:
            mappings = AssessmentToLO.objects.filter(learning_outcome=lo).select_related('assessment')
            total_weighted_score = 0.0
            total_weight = 0.0

            for mapping in mappings:
                grade_record = StudentGrade.objects.filter(student=student, assessment=mapping.assessment).first()
                if grade_record is not None:
                    total_weighted_score += grade_record.score * mapping.weight
                    total_weight += mapping.weight

            if total_weight > 0:
                lo_scores[lo.code] = round(total_weighted_score / total_weight, 2)
            else:
                lo_scores[lo.code] = None

        return lo_scores

    @staticmethod
    def calculate_student_po_scores_for_course(student: Student, course: Course):
        """
        Calculates PO scores contributed by a single course.
        PO Score = Sum(LO Score * Weight) / Sum(Weights)
        """
        lo_scores = POCalculator.calculate_student_lo_scores(student, course)
        po_scores = {}

        program_outcomes = ProgramOutcome.objects.all()

        for po in program_outcomes:
            mappings = LOToPO.objects.filter(
                program_outcome=po,
                learning_outcome__course=course
            ).select_related('learning_outcome')

            total_weighted_score = 0.0
            total_weight = 0.0

            for mapping in mappings:
                lo_code = mapping.learning_outcome.code
                lo_score = lo_scores.get(lo_code)

                if lo_score is not None:
                    total_weighted_score += lo_score * mapping.weight
                    total_weight += mapping.weight

            if total_weight > 0:
                po_scores[po.code] = round(total_weighted_score / total_weight, 2)

        return po_scores