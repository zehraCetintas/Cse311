from collections import defaultdict

from main.models import (
    AssessmentToLO,
    Course,
    LOToPO,
    ProgramOutcome,
    StudentGrade,
)


def compute_student_scores(course_ids=None):
    """
    POCalculator ile aynı formüller, ama tüm veriyi birkaç sorguyla çeker.
    Döndürür: {student_id: {"courses": {course_id: {"lo": {...}, "po": {...}}},
                            "po": {po_code: genel_skor}}}
    """
    a2lo_qs = AssessmentToLO.objects.select_related("learning_outcome")
    lo2po_qs = LOToPO.objects.select_related("learning_outcome", "program_outcome")
    grade_qs = StudentGrade.objects.select_related("assessment")
    if course_ids is not None:
        a2lo_qs = a2lo_qs.filter(learning_outcome__course_id__in=course_ids)
        lo2po_qs = lo2po_qs.filter(learning_outcome__course_id__in=course_ids)
        grade_qs = grade_qs.filter(assessment__course_id__in=course_ids)

    lo_inputs = defaultdict(list)  # lo_id -> [(assessment_id, weight)]
    los_by_course = defaultdict(set)  # course_id -> {lo_id}
    for m in a2lo_qs:
        lo_inputs[m.learning_outcome_id].append((m.assessment_id, m.weight))
        los_by_course[m.learning_outcome.course_id].add(m.learning_outcome_id)

    po_inputs = defaultdict(lambda: defaultdict(list))  # course_id -> po_code -> [(lo_id, weight)]
    mappings_by_course = defaultdict(list)  # course_id -> [(lo_id, po_code, weight)]
    for m in lo2po_qs:
        course_id = m.learning_outcome.course_id
        po_code = m.program_outcome.code
        po_inputs[course_id][po_code].append((m.learning_outcome_id, m.weight))
        mappings_by_course[course_id].append((m.learning_outcome_id, po_code, m.weight))

    grades = defaultdict(dict)  # student_id -> {assessment_id: score}
    grade_courses = defaultdict(set)  # student_id -> {course_id}
    for g in grade_qs:
        grades[g.student_id][g.assessment_id] = g.score
        grade_courses[g.student_id].add(g.assessment.course_id)

    result = {}
    for student_id, scores in grades.items():
        courses = {}
        totals = defaultdict(float)
        weights = defaultdict(float)
        for course_id in grade_courses[student_id]:
            lo_scores = {}
            for lo_id in los_by_course.get(course_id, ()):
                num = den = 0.0
                for assessment_id, w in lo_inputs[lo_id]:
                    if assessment_id in scores:
                        num += scores[assessment_id] * w
                        den += w
                lo_scores[lo_id] = round(num / den, 2) if den > 0 else None

            po_scores = {}
            for po_code, items in po_inputs[course_id].items():
                num = den = 0.0
                for lo_id, w in items:
                    s = lo_scores.get(lo_id)
                    if s is not None:
                        num += s * w
                        den += w
                if den > 0:
                    po_scores[po_code] = round(num / den, 2)

            for lo_id, po_code, w in mappings_by_course[course_id]:
                if lo_scores.get(lo_id) is None or po_code not in po_scores:
                    continue
                totals[po_code] += po_scores[po_code] * w
                weights[po_code] += w

            courses[course_id] = {"lo": lo_scores, "po": po_scores}

        result[student_id] = {
            "courses": courses,
            "po": {code: totals[code] / weights[code] for code in weights if weights[code]},
        }
    return result


def department_po_averages(exclude_prefix="ACU"):
    """head_dashboard'daki PO ortalamalarıyla aynı mantık."""
    course_ids = list(
        Course.objects.exclude(code__istartswith=exclude_prefix).values_list("pk", flat=True)
    )
    sums = defaultdict(float)
    counts = defaultdict(int)
    for data in compute_student_scores(course_ids).values():
        for po_code, score in data["po"].items():
            sums[po_code] += score
            counts[po_code] += 1
    return {code: round(sums[code] / counts[code], 2) for code in counts}


def po_course_breakdown(po_code, exclude_prefix="ACU", threshold=50.0):
    """Bir PO için ders bazlı döküm: hangi ders PO'yu yükseltiyor, hangisi düşürüyor."""
    mappings = (
        LOToPO.objects.filter(program_outcome__code=po_code)
        .exclude(learning_outcome__course__code__istartswith=exclude_prefix)
        .select_related("learning_outcome__course")
    )
    courses = {}
    los_by_course = defaultdict(list)
    for m in mappings:
        course = m.learning_outcome.course
        courses[course.pk] = course
        los_by_course[course.pk].append(
            {"code": m.learning_outcome.code, "weight": m.weight}
        )

    scores = compute_student_scores(list(courses))
    dept_average = department_po_averages(exclude_prefix).get(po_code)

    rows = []
    for course_id, course in courses.items():
        values = [
            data["courses"][course_id]["po"][po_code]
            for data in scores.values()
            if course_id in data["courses"]
            and po_code in data["courses"][course_id]["po"]
        ]
        average = round(sum(values) / len(values), 2) if values else None
        rows.append(
            {
                "course": course,
                "los": los_by_course[course_id],
                "student_count": len(values),
                "average": average,
                "lowest": min(values) if values else None,
                "below_threshold": sum(1 for v in values if v < threshold),
                "difference": (
                    round(average - dept_average, 2)
                    if average is not None and dept_average is not None
                    else None
                ),
            }
        )
    rows.sort(key=lambda r: (r["average"] is None, r["average"] or 0))
    return {"rows": rows, "dept_average": dept_average}


def uncovered_pos(exclude_prefix="ACU"):
    """Hiçbir derse bağlanmamış PO'lar (örn. PO9)."""
    covered = set(
        LOToPO.objects.exclude(learning_outcome__course__code__istartswith=exclude_prefix)
        .values_list("program_outcome__code", flat=True)
    )
    return [po for po in ProgramOutcome.objects.order_by("code") if po.code not in covered]