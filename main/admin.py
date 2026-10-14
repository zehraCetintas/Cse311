from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, ProgramOutcome, Course, LearningOutcome,
    Assessment, AssessmentToLO, LOToPO, Student, StudentGrade
)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role Details', {'fields': ('role',)}),
    )
    list_display = ('username', 'email', 'role', 'is_staff')
    list_filter = ('role', 'is_staff')


@admin.register(ProgramOutcome)
class ProgramOutcomeAdmin(admin.ModelAdmin):
    list_display = ('code', 'title')
    search_fields = ('code', 'title')


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'instructor')
    list_filter = ('instructor',)
    search_fields = ('code', 'title')


@admin.register(LearningOutcome)
class LearningOutcomeAdmin(admin.ModelAdmin):
    list_display = ('code', 'course', 'description')
    list_filter = ('course',)


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'course', 'weight')
    list_filter = ('course',)


@admin.register(AssessmentToLO)
class AssessmentToLOAdmin(admin.ModelAdmin):
    list_display = ('assessment', 'learning_outcome', 'weight')
    list_filter = ('assessment__course',)


@admin.register(LOToPO)
class LOToPOAdmin(admin.ModelAdmin):
    list_display = ('learning_outcome', 'program_outcome', 'weight')
    list_filter = ('program_outcome',)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_number', 'first_name', 'last_name')
    search_fields = ('student_number', 'first_name', 'last_name')


@admin.register(StudentGrade)
class StudentGradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'assessment', 'score')
    list_filter = ('assessment__course', 'assessment')
