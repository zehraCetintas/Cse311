from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator


# 1. Custom User Model & Roles
class User(AbstractUser):
    class Role(models.TextChoices):
        HEAD_OF_FACULTY = 'HEAD', 'Head of Faculty / Department Head'
        INSTRUCTOR = 'INSTRUCTOR', 'Course Instructor'
        STUDENT = 'STUDENT', 'Student'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.INSTRUCTOR
    )

    def is_head(self):
        return self.role == self.Role.HEAD_OF_FACULTY

    def is_instructor(self):
        return self.role == self.Role.INSTRUCTOR


# 2. Program Outcomes (Department-level outcomes: PO1 ... PO11)
class ProgramOutcome(models.Model):
    code = models.CharField(max_length=10, unique=True)  # e.g., PO1, PO2
    title = models.CharField(max_length=255)
    description = models.TextField()

    def __str__(self):
        return f"{self.code} - {self.title}"


# 3. Courses
class Course(models.Model):
    code = models.CharField(max_length=20, unique=True)  # e.g., CSE 311
    title = models.CharField(max_length=255)            # e.g., Software
    instructor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_courses'
    )
    syllabus_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"{self.code}: {self.title}"


# 4. Learning Outcomes (Course-level outcomes: LO1, LO2...)
class LearningOutcome(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='learning_outcomes')
    code = models.CharField(max_length=20)  # e.g., LO1, LO2
    description = models.TextField()

    def __str__(self):
        return f"{self.course.code} - {self.code}"


# 5. Assessments (Midterm, Project, Final...)
class Assessment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='assessments')
    name = models.CharField(max_length=100)  # e.g., Midterm, Project
    weight = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Weight percentage within the course (0-100)"
    )

    def __str__(self):
        return f"{self.course.code} - {self.name} (%{self.weight})"


# 6. Mappings & Weights
# Assessment -> Learning Outcome Mapping (e.g., Midterm -> LO1 60%, LO2 40%)
class AssessmentToLO(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='lo_mappings')
    learning_outcome = models.ForeignKey(LearningOutcome, on_delete=models.CASCADE, related_name='assessment_mappings')
    weight = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Contribution percentage to the learning outcome (0-100)"
    )

    class Meta:
        unique_together = ('assessment', 'learning_outcome')

    def __str__(self):
        return f"{self.assessment} -> {self.learning_outcome.code} (%{self.weight})"


# Learning Outcome -> Program Outcome Mapping (Percentage-based: 0-100%)
class LOToPO(models.Model):
    learning_outcome = models.ForeignKey(LearningOutcome, on_delete=models.CASCADE, related_name='po_mappings')
    program_outcome = models.ForeignKey(ProgramOutcome, on_delete=models.CASCADE, related_name='lo_mappings')
    weight = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        help_text="Contribution percentage to the program outcome (0-100)"
    )

    class Meta:
        unique_together = ('learning_outcome', 'program_outcome')

    def __str__(self):
        return f"{self.learning_outcome} -> {self.program_outcome.code} (%{self.weight})"


# 7. Students & Grades
class Student(models.Model):
    student_number = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='student_profile'
    )

    def __str__(self):
        return f"{self.student_number} - {self.first_name} {self.last_name}"


class StudentGrade(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='grades')
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='student_grades')
    score = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )

    class Meta:
        unique_together = ('student', 'assessment')

    def __str__(self):
        return f"{self.student} - {self.assessment.name}: {self.score}"