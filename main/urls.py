from django.urls import path
from . import views

app_name = 'main'

urlpatterns = [
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
]