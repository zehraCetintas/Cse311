from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views.defaults import server_error

from main.models import User


class ErrorPagesTestCase(TestCase):
    def setUp(self):
        self.instructor = User.objects.create_user(
            username="instructor", password="test-password", role=User.Role.INSTRUCTOR
        )
        self.head = User.objects.create_user(
            username="head", password="test-password", role=User.Role.HEAD_OF_FACULTY
        )
        self.student = User.objects.create_user(
            username="student", password="test-password", role=User.Role.STUDENT
        )

    def test_forbidden_page_shows_reason_and_link_to_own_dashboard(self):
        self.client.force_login(self.instructor)

        response = self.client.get(reverse("head_dashboard"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertContains(response, "Only heads of faculty can access this dashboard.", status_code=403)
        self.assertContains(response, f'href="{reverse("instructor_dashboard")}"', status_code=403)

    def test_instructor_only_views_use_forbidden_page(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("instructor_dashboard"))

        self.assertTemplateUsed(response, "403.html")
        self.assertContains(response, "Only instructors can access the instructor workspace.", status_code=403)
        self.assertContains(response, f'href="{reverse("student_dashboard")}"', status_code=403)

    def test_not_found_page_for_anonymous_user_links_to_login(self):
        response = self.client.get("/this-page-does-not-exist/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Go to login", status_code=404)
        self.assertContains(response, f'href="{reverse("login")}"', status_code=404)

    def test_not_found_page_for_logged_in_user_links_to_dashboard(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("po_detail", args=["PO99"]))

        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Back to your dashboard", status_code=404)
        self.assertContains(response, f'href="{reverse("head_dashboard")}"', status_code=404)

    def test_server_error_page_renders_without_request_context(self):
        response = server_error(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 500)
        self.assertIn(b"Something went wrong", response.content)
