from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from .models import Student, Course
from .services.calculator import POCalculator

@login_required
def student_dashboard(request):
    student = get_object_or_404(Student, user=request.user)
    
    courses = Course.objects.all()
    
    course_reports = []
    for course in courses:
        lo_scores = POCalculator.calculate_student_lo_scores(student, course)
        po_scores = POCalculator.calculate_student_po_scores_for_course(student, course)
        
        course_reports.append({
            'course': course,
            'lo_scores': lo_scores,
            'po_scores': po_scores,
        })
        
    context = {
        'student': student,
        'course_reports': course_reports,
    }
    
    return render(request, 'main/student_dashboard.html', context)
