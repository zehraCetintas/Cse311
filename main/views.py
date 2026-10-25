import random
import re
import secrets
import string
from functools import wraps
from math import isclose
from urllib.parse import urlencode, urlsplit
from zipfile import BadZipFile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.views.decorators.http import require_POST
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from openpyxl.utils.exceptions import InvalidFileException

from main.models import (
    Assessment,
    Course,
    LearningOutcome,
    LOToPO,
    ProgramOutcome,
    Student,
    StudentGrade,
    User,
)
from main.services.bologna_scraper import BolognaScraperService
from main.services.calculator import POCalculator
from main.services.grade_importer import GradeImporterService
from main.services import analytics as analytics_service

def _dashboard_url_for_user(user):
    if user.role == User.Role.HEAD_OF_FACULTY or user.is_superuser:
        return reverse("head_dashboard")
    if user.role == User.Role.INSTRUCTOR:
        return reverse("instructor_dashboard")
    if user.role == User.Role.STUDENT:
        return reverse("student_dashboard")
    return reverse("login")


def _set_captcha(request):
    first = secrets.randbelow(50) + 1
    second = secrets.randbelow(50) + 1
    operation = secrets.choice(("+", "-"))
    expected_result = first + second if operation == "+" else first - second
    request.session["captcha_result"] = expected_result
    return f"{first} {operation} {second} = ?"


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_url_for_user(request.user))

    captcha_question = ""
    if request.method == "POST":
        username = request.POST.get("number", "").strip()
        password = request.POST.get("password", "")
        captcha_answer = request.POST.get("captcha_answer", "").strip()
        expected_answer = request.session.pop("captcha_result", None)

        try:
            is_captcha_valid = (
                expected_answer is not None
                and int(captcha_answer) == expected_answer
            )
        except ValueError:
            is_captcha_valid = False

        if not is_captcha_valid:
            messages.error(request, "The math verification answer is incorrect.")
        elif not username or not password:
            messages.error(request, "Enter your number and password.")
        else:
            user = authenticate(
                request, username=username, password=password
            )
            if user is None:
                messages.error(request, "The number or password is incorrect.")
            elif not user.is_active:
                messages.error(request, "This account is inactive.")
            else:
                login(request, user)
                return redirect(_dashboard_url_for_user(user))
        captcha_question = _set_captcha(request)
    else:
        captcha_question = _set_captcha(request)

    return render(
        request,
        "registration/login.html",
        {
            "captcha_question": captcha_question,
            "active_tab": request.GET.get("tab", "login"),
        },
    )


def reset_password(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_url_for_user(request.user))
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])

    reset_errors = []
    reset_number = ""
    reset_email = ""
    if request.method == "POST":
        reset_number = request.POST.get("number", "").strip()
        reset_email = request.POST.get("email", "").strip()
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if not re.fullmatch(r"\d{9}", reset_number):
            reset_errors.append("Enter your 9-digit ID number.")
        if not reset_email:
            reset_errors.append("Enter the email address registered to your account.")
        if not re.search(r"[A-Za-z]", new_password) or not re.search(
            r"\d", new_password
        ):
            reset_errors.append(
                "Your new password must contain at least one letter and one number."
            )
        if len(new_password) < 8:
            reset_errors.append("Your new password must be at least 8 characters.")
        if new_password != confirm_password:
            reset_errors.append("The new password and confirmation do not match.")

        if not reset_errors:
            user = User.objects.filter(
                username=reset_number,
                email__iexact=reset_email,
                is_active=True,
            ).first()
            if user is None:
                reset_errors.append(
                    "No active account found with the provided ID number and email combination."
                )
            else:
                user.set_password(new_password)
                user.save(update_fields=["password"])
                messages.success(
                    request,
                    "Your password has been successfully updated. "
                    "You can now log in with your new password.",
                )
                return redirect("login")

    return render(
        request,
        "registration/login.html",
        {
            "captcha_question": _set_captcha(request),
            "active_tab": "reset",
            "reset_errors": reset_errors,
            "reset_number": reset_number,
            "reset_email": reset_email,
        },
    )


def _generate_temporary_password():
    required_chars = (
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
    )
    alphabet = string.ascii_letters + string.digits
    length = secrets.choice(range(8, 11))
    characters = list(required_chars)
    characters.extend(
        secrets.choice(alphabet) for _ in range(length - len(required_chars))
    )
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def register_student(request):
    if request.method != "POST":
        return redirect(f"{reverse('login')}?tab=register")
    if request.user.is_authenticated:
        return redirect(_dashboard_url_for_user(request.user))

    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip()
    role = request.POST.get("role", User.Role.STUDENT)
    if role not in (User.Role.STUDENT, User.Role.INSTRUCTOR):
        messages.error(request, "Choose Student or Instructor registration.")
        return redirect(f"{reverse('login')}?tab=register")
    if not first_name or not last_name or not email:
        messages.error(request, "Enter your first name, last name, and email.")
        return redirect(f"{reverse('login')}?tab=register")
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, "Enter a valid email address.")
        return redirect(f"{reverse('login')}?tab=register")
    if User.objects.filter(email__iexact=email).exists():
        messages.error(request, "An account with that email address already exists.")
        return redirect(f"{reverse('login')}?tab=register")

    for _ in range(5):
        student_number = str(random.randint(100000000, 999999999))
        if User.objects.filter(username=student_number).exists():
            continue
        if Student.objects.filter(student_number=student_number).exists():
            continue

        temporary_password = _generate_temporary_password()
        try:
            with transaction.atomic():
                user = User(
                    username=student_number,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    is_active=True,
                )
                user.set_password(temporary_password)
                user.save()
                if role == User.Role.STUDENT:
                    Student.objects.create(
                        user=user,
                        student_number=student_number,
                        first_name=first_name,
                        last_name=last_name,
                    )
        except IntegrityError:
            continue

        if role == User.Role.INSTRUCTOR:
            messages.success(
                request,
                "Instructor Registration Successful! "
                f"Staff Number: {student_number}, "
                f"Temporary Password: {temporary_password}.",
            )
        else:
            messages.success(
                request,
                "Registration Complete! "
                f"Number: {student_number}, Temporary Password: "
                f"{temporary_password}. Please note it!",
            )
        return redirect(f"{reverse('login')}?tab=register")

    messages.error(
        request,
        "We could not generate a unique student number. Please try again.",
    )
    return redirect(f"{reverse('login')}?tab=register")


def instructor_required(view):
    @login_required
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        if request.user.role != User.Role.INSTRUCTOR:
            return HttpResponseForbidden(
                "Only instructors can access the instructor workspace."
            )
        return view(request, *args, **kwargs)

    return wrapped_view


def _assigned_courses(user):
    return Course.objects.filter(instructor=user).order_by("code")


def _dashboard_redirect(course_id=None):
    url = reverse("instructor_dashboard")
    if course_id is not None:
        return f"{url}?{urlencode({'course_id': course_id})}"
    return url


def _submitted_course_id(request):
    course_id = request.POST.get("course_id")
    if (
        course_id
        and course_id.isdecimal()
        and _assigned_courses(request.user).filter(pk=course_id).exists()
    ):
        return course_id
    return None


@instructor_required
def instructor_dashboard(request):
    courses = _assigned_courses(request.user)
    selected_course = None
    selected_id = request.GET.get("course_id")
    if selected_id and selected_id.isdecimal():
        selected_course = courses.filter(pk=selected_id).first()
    if selected_course is None:
        selected_course = courses.first()

    assessments = (
        BolognaScraperService.deduplicate_assessments(
            assessment
            for assessment in selected_course.assessments.order_by("name")
            if BolognaScraperService.is_component_assessment(assessment.name)
        )
        if selected_course
        else []
    )
    total_assessment_weight = sum(
        assessment.weight for assessment in assessments
    )

    return render(
        request,
        "instructor/dashboard.html",
        {
            "courses": courses,
            "selected_course": selected_course,
            "assessments": assessments,
            "total_assessment_weight": total_assessment_weight,
            "assessment_weight_is_valid": isclose(
                total_assessment_weight, 100, abs_tol=0.01
            ),
        },
    )


@login_required
@require_POST
def import_bologna_course(request):
    if (
        request.user.role != User.Role.HEAD_OF_FACULTY
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden(
            "Only heads of faculty can import Bologna courses."
        )

    syllabus_url = request.POST.get("syllabus_url", "").strip()
    parsed_url = urlsplit(syllabus_url)
    if (
        parsed_url.scheme not in ("http", "https")
        or parsed_url.hostname != "obs.acibadem.edu.tr"
    ):
        messages.error(
            request,
            "Enter a valid Bologna syllabus URL from obs.acibadem.edu.tr.",
        )
        return redirect("head_dashboard")

    result = BolognaScraperService.scrape_course_data(syllabus_url)
    if not result.get("success"):
        messages.error(
            request,
            f"Course import failed: {result.get('error') or 'No course data was found.'}",
        )
        return redirect("head_dashboard")

    try:
        synced_courses = BolognaScraperService.sync_to_database(result)
    except ValueError as exc:
        messages.error(request, f"Course import failed: {exc}")
        return redirect("head_dashboard")

    if not isinstance(synced_courses, list):
        synced_courses = [synced_courses]
    if not synced_courses:
        messages.error(request, "Course import failed: no courses were synchronized.")
        return redirect("head_dashboard")

    for course in synced_courses:
        course.syllabus_url = syllabus_url
        course.save(update_fields=["syllabus_url"])
    if len(synced_courses) == 1:
        messages.success(
            request,
            f"Imported {synced_courses[0].code}; assign an instructor in the workspace below.",
        )
    else:
        messages.success(
            request,
            f"Imported {len(synced_courses)} courses; assign instructors in the workspace below.",
        )
    return redirect("head_dashboard")


@login_required
@require_POST
def assign_course_instructor(request):
    if (
        request.user.role != User.Role.HEAD_OF_FACULTY
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden(
            "Only heads of faculty can assign instructors to courses."
        )

    course_id = request.POST.get("course_id", "")
    if not course_id.isdecimal():
        messages.error(request, "Choose a valid course.")
        return redirect("head_dashboard")
    course = get_object_or_404(Course, pk=course_id)

    instructor_id = request.POST.get("instructor_id", "")
    if instructor_id:
        if not instructor_id.isdecimal():
            messages.error(request, "Choose a valid instructor.")
            return redirect("head_dashboard")
        instructor = User.objects.filter(
            pk=instructor_id,
            role=User.Role.INSTRUCTOR,
            is_active=True,
        ).first()
        if instructor is None:
            messages.error(request, "Choose a registered active instructor.")
            return redirect("head_dashboard")
    else:
        instructor = None

    course.instructor = instructor
    course.save(update_fields=["instructor"])
    if instructor:
        messages.success(
            request,
            f"{course.code} assigned to "
            f"{instructor.get_full_name() or instructor.username}.",
        )
    else:
        messages.success(request, f"{course.code} is now unassigned.")
    return redirect("head_dashboard")


@instructor_required
def upload_grades(request):
    course_id = _submitted_course_id(request)
    assessment_id = request.POST.get("assessment_id")
    if not assessment_id or not assessment_id.isdecimal():
        messages.error(request, "Choose a valid assessment.")
        return redirect(_dashboard_redirect(course_id))
    assessment = (
        Assessment.objects.filter(course__instructor=request.user)
        .filter(pk=assessment_id)
        .first()
    )
    if assessment is None or not BolognaScraperService.is_component_assessment(
        assessment.name
    ):
        messages.error(request, "That assessment is not assigned to your courses.")
        return redirect(_dashboard_redirect(course_id))
    grades_file = request.FILES.get("grades_file")
    if grades_file is None:
        messages.error(request, "Choose an Excel (.xlsx) file to upload.")
        return redirect(_dashboard_redirect(course_id or assessment.course_id))
    if not grades_file.name.lower().endswith(".xlsx"):
        messages.error(request, "Only Excel .xlsx files are supported.")
        return redirect(_dashboard_redirect(assessment.course_id))

    try:
        result = GradeImporterService.import_excel_grades(assessment, grades_file)
    except (BadZipFile, InvalidFileException, ValueError, IndexError) as exc:
        messages.error(request, f"Grade import failed; no grades were saved: {exc}")
        return redirect(_dashboard_redirect(assessment.course_id))

    if not result["success"]:
        details = " ".join(result["errors"])
        messages.error(
            request,
            f"No grades were imported; no changes were saved. {details}",
        )
    else:
        messages.success(
            request,
            "Grade import complete: "
            f"{result['created']} created, {result['updated']} updated.",
        )
    return redirect(_dashboard_redirect(assessment.course_id))


@login_required
def student_dashboard(request):
    if request.user.role == User.Role.STUDENT:
        student = get_object_or_404(Student, user=request.user)
    elif request.user.role in (
        User.Role.HEAD_OF_FACULTY,
        User.Role.INSTRUCTOR,
    ):
        student_id = request.GET.get("student_id")
        if not student_id:
            return render(
                request,
                "student/dashboard.html",
                {
                    "students": Student.objects.order_by(
                        "last_name", "first_name", "student_number"
                    ),
                    "selected_student": None,
                    "po_labels": [f"PO{number}" for number in range(1, 12)],
                    "po_scores": [None] * 11,
                    "course_breakdowns": [],
                    "faculty": "Not specified",
                    "department": "Not specified",
                    "learning_outcomes": [],
                },
            )
        student = get_object_or_404(Student, pk=student_id)
    else:
        return HttpResponseForbidden(
            "Only students, instructors, and heads of faculty can access this page."
        )

    grade_rows = list(
        StudentGrade.objects.filter(student=student)
        .select_related("assessment", "assessment__course")
        .order_by("assessment__course__code", "assessment__name")
    )
    course_ids = set(student.enrolled_courses.values_list("pk", flat=True))
    course_ids.update(grade.assessment.course_id for grade in grade_rows)
    courses = list(Course.objects.filter(pk__in=course_ids).order_by("code"))
    course_breakdowns = []
    course_lo_scores = {}
    course_po_scores = {}
    for course in courses:
        lo_scores = POCalculator.calculate_student_lo_scores(student, course)
        po_scores = POCalculator.calculate_student_po_scores_for_course(
            student, course
        )
        course_lo_scores[course.pk] = lo_scores
        course_po_scores[course.pk] = po_scores
        course_breakdowns.append(
            {
                "course": course,
                "lo_scores": lo_scores,
                "grades": [
                    grade
                    for grade in grade_rows
                    if grade.assessment.course_id == course.pk
                ],
            }
        )

    po_labels = [f"PO{number}" for number in range(1, 12)]
    po_weighted_totals = {label: 0.0 for label in po_labels}
    po_total_weights = {label: 0.0 for label in po_labels}
    mappings = LOToPO.objects.filter(
        learning_outcome__course_id__in=course_ids,
        program_outcome__code__in=po_labels,
    ).select_related("learning_outcome", "program_outcome")
    for mapping in mappings:
        course_id = mapping.learning_outcome.course_id
        lo_score = course_lo_scores[course_id].get(
            mapping.learning_outcome.code
        )
        course_po_score = course_po_scores[course_id].get(
            mapping.program_outcome.code
        )
        if lo_score is None or course_po_score is None:
            continue
        po_weighted_totals[mapping.program_outcome.code] += (
            course_po_score * mapping.weight
        )
        po_total_weights[mapping.program_outcome.code] += mapping.weight

    po_scores = [
        round(po_weighted_totals[label] / po_total_weights[label], 2)
        if po_total_weights[label]
        else None
        for label in po_labels
    ]

    return render(
        request,
        "student/dashboard.html",
        {
            "students": None,
            "selected_student": student,
            "student": student,
            "courses": courses,
            "course_breakdowns": course_breakdowns,
            "po_labels": po_labels,
            "po_scores": po_scores,
            "faculty": student.faculty or "Not specified",
            "department": student.department or "Not specified",
            "full_name": f"{student.first_name} {student.last_name}".strip(),
            "avatar_url": (
                student.profile_picture.url if student.profile_picture else None
            ),
            "enrolled_courses": courses,
            "learning_outcomes": (
                LearningOutcome.objects.filter(course_id__in=course_ids)
                .select_related("course")
                .order_by("course__code", "code")
            ),
        },
    )


@login_required
def student_program_outcomes(request):
    if request.user.role != User.Role.STUDENT:
        return HttpResponseForbidden(
            "Only students can access the program outcome list."
        )

    get_object_or_404(Student, user=request.user)
    return render(
        request,
        "student/program_outcomes.html",
        {"program_outcomes": ProgramOutcome.objects.order_by("code")},
    )


@login_required
@require_POST
def update_profile_picture(request):
    image = request.FILES.get("profile_picture")
    if image is None:
        messages.error(request, "Choose an image to upload.")
        return redirect(_dashboard_url_for_user(request.user))

    from django.forms import ImageField

    try:
        cleaned_image = ImageField().clean(image)
    except ValidationError as exc:
        messages.error(
            request,
            "Profile picture upload failed: " + " ".join(exc.messages),
        )
        return redirect(_dashboard_url_for_user(request.user))

    request.user.profile_picture = cleaned_image
    request.user.save(update_fields=["profile_picture"])
    if request.user.role == User.Role.STUDENT:
        student = get_object_or_404(Student, user=request.user)
        student.profile_picture = request.user.profile_picture
        student.save(update_fields=["profile_picture"])
    messages.success(request, "Profile picture updated.")
    return redirect(_dashboard_url_for_user(request.user))


@login_required
def head_dashboard(request):
    if (
        request.user.role != User.Role.HEAD_OF_FACULTY
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden(
            "Only heads of faculty can access this dashboard."
        )

    courses = list(
        Course.objects.exclude(code__istartswith="ACU")
        .select_related("instructor")
        .prefetch_related("assessments", "assessments__student_grades")
        .order_by("code")
    )
    course_audit = []
    for course in courses:
        assessments = BolognaScraperService.deduplicate_assessments(
            assessment
            for assessment in course.assessments.all()
            if BolognaScraperService.is_component_assessment(assessment.name)
        )
        total_weight = sum(assessment.weight for assessment in assessments)
        student_count = (
            StudentGrade.objects.filter(assessment__course=course)
            .values("student_id")
            .distinct()
            .count()
        )
        compliant = isclose(total_weight, 100, abs_tol=0.01)
        course_audit.append(
            {
                "course": course,
                "instructor": course.instructor,
                "assessment_total_weight": total_weight,
                "assessment_weight_is_valid": compliant,
                "student_count": student_count,
                "status": (
                    "Compliant"
                    if compliant
                    else "Incomplete assessment weights"
                    if assessments
                    else "No assessments configured"
                ),
            }
        )

    po_labels = [f"PO{number}" for number in range(1, 12)]
    po_score_totals = {label: 0.0 for label in po_labels}
    po_student_counts = {label: 0 for label in po_labels}
    students_with_grades = Student.objects.filter(
        grades__isnull=False
    ).distinct()
    outcome_mappings = LOToPO.objects.filter(
        learning_outcome__course_id__in=[course.pk for course in courses],
        program_outcome__code__in=po_labels,
    ).select_related("learning_outcome", "program_outcome")
    mappings_by_course = {}
    for mapping in outcome_mappings:
        mappings_by_course.setdefault(mapping.learning_outcome.course_id, []).append(
            mapping
        )
    courses_by_id = {course.pk: course for course in courses}

    for student in students_with_grades:
        grades = StudentGrade.objects.filter(student=student).select_related(
            "assessment"
        )
        student_course_ids = {
            grade.assessment.course_id
            for grade in grades
            if grade.assessment.course_id in mappings_by_course
        }
        weighted_totals = {label: 0.0 for label in po_labels}
        total_weights = {label: 0.0 for label in po_labels}
        for course_id in student_course_ids:
            course = courses_by_id[course_id]
            lo_scores = POCalculator.calculate_student_lo_scores(student, course)
            course_po_scores = POCalculator.calculate_student_po_scores_for_course(
                student, course
            )
            for mapping in mappings_by_course[course_id]:
                if lo_scores.get(mapping.learning_outcome.code) is None:
                    continue
                po_code = mapping.program_outcome.code
                course_po_score = course_po_scores.get(po_code)
                if course_po_score is None:
                    continue
                weighted_totals[po_code] += course_po_score * mapping.weight
                total_weights[po_code] += mapping.weight

        for po_code in po_labels:
            if total_weights[po_code]:
                po_score_totals[po_code] += (
                    weighted_totals[po_code] / total_weights[po_code]
                )
                po_student_counts[po_code] += 1

    po_averages = [
        round(po_score_totals[label] / po_student_counts[label], 2)
        if po_student_counts[label]
        else None
        for label in po_labels
    ]
    outcomes_by_code = {
        outcome.code: outcome
        for outcome in ProgramOutcome.objects.filter(code__in=po_labels)
    }
    po_summary = []
    for label, score in zip(po_labels, po_averages):
        outcome = outcomes_by_code.get(label)
        po_summary.append(
            {
                "label": label,
                "score": score,
                "title": outcome.title if outcome else "",
                "description": outcome.description if outcome else "",
            }
        )
    accreditation_threshold = 50.0
    po_warnings = [
        outcome
        for outcome in po_summary
        if outcome["score"] is not None
        and outcome["score"] < accreditation_threshold
    ]
    overall_scores = [score for score in po_averages if score is not None]
    overall_department_score = (
        round(sum(overall_scores) / len(overall_scores), 2)
        if overall_scores
        else None
    )

    return render(
        request,
        "faculty_head/dashboard.html",
        {
            "total_courses": len(courses),
            "total_instructors": User.objects.filter(
                role=User.Role.INSTRUCTOR, is_active=True
            ).count(),
            "total_students": Student.objects.count(),
            "overall_department_score": overall_department_score,
            "po_labels": po_labels,
            "po_averages": po_averages,
            "po_summary": po_summary,
            "po_warnings": po_warnings,
            "course_audit": course_audit,
            "accreditation_threshold": accreditation_threshold,
            "instructors": User.objects.filter(
                role=User.Role.INSTRUCTOR, is_active=True
            ).order_by("first_name", "last_name", "username"),
        },
    )


@login_required
def po_detail(request, po_code):
    if (
        request.user.role != User.Role.HEAD_OF_FACULTY
        and not request.user.is_superuser
    ):
        return HttpResponseForbidden("Only heads of faculty can access this page.")

    outcome = get_object_or_404(ProgramOutcome, code=po_code)
    breakdown = analytics_service.po_course_breakdown(po_code)
    uncovered = {po.code for po in analytics_service.uncovered_pos()}
    return render(
        request,
        "faculty_head/po_detail.html",
        {
            "outcome": outcome,
            "rows": breakdown["rows"],
            "dept_average": breakdown["dept_average"],
            "is_uncovered": po_code in uncovered,
        },
    )