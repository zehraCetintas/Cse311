from django.contrib.auth.views import LogoutView
from django.urls import path

from main import views


urlpatterns = [
    path("", views.login_view, name="login"),
    path("reset-password/", views.reset_password, name="reset_password"),
    path("register/", views.register_student, name="register_student"),
    path("instructor/", views.instructor_dashboard, name="instructor_dashboard"),
    path("student/", views.student_dashboard, name="student_dashboard"),
    path(
        "student/program-outcomes/",
        views.student_program_outcomes,
        name="student_program_outcomes",
    ),
    path(
        "student/profile-picture/",
        views.update_profile_picture,
        name="update_student_profile_picture",
    ),
    path(
        "profile-picture/",
        views.update_profile_picture,
        name="update_profile_picture",
    ),
    path("faculty-head/", views.head_dashboard, name="head_dashboard"),
    path("faculty-head/po/<str:po_code>/", views.po_detail, name="po_detail"),
    path(
        "faculty-head/import-course/",
        views.import_bologna_course,
        name="import_bologna_course",
    ),
    path(
        "faculty-head/assign-course/",
        views.assign_course_instructor,
        name="assign_course_instructor",
    ),
    path("instructor/upload-grades/", views.upload_grades, name="upload_grades"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
]
from django.urls import path
from . import views

app_name = 'main'

urlpatterns = [
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
]
