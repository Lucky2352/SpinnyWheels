from django.test import TestCase
from django.urls import reverse


class Phase4PageRenderTests(TestCase):
    def test_employees_page_renders_with_role_gated_sidebar(self):
        response = self.client.get(reverse("employees"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-owner-only")
        self.assertContains(response, "data-staff-only")
        self.assertContains(response, "data-technician-only")
        self.assertContains(response, reverse("employees"))
        self.assertContains(response, reverse("technicians"))
        self.assertContains(response, reverse("work_queue"))
        self.assertContains(response, reverse("my_work"))

    def test_technicians_page_renders(self):
        response = self.client.get(reverse("technicians"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "technicianModal")

    def test_work_queue_page_renders(self):
        response = self.client.get(reverse("work_queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-request-list")
        self.assertContains(response, "data-appointment-list")

    def test_my_work_page_renders(self):
        response = self.client.get(reverse("my_work"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-assignment-list")

    def test_sidebar_visibility_hooks_cover_every_staff_page(self):
        response = self.client.get(reverse("dashboard"))
        body = response.content.decode()

        self.assertIn(f'href="{reverse("employees")}" data-owner-only', body)
        self.assertIn(f'href="{reverse("technicians")}" data-owner-only', body)
        self.assertIn(f'href="{reverse("work_queue")}" data-staff-only', body)
        self.assertIn(f'href="{reverse("my_work")}" data-technician-only', body)

    def test_customer_navigation_is_unchanged(self):
        body = self.client.get(reverse("dashboard")).content.decode()

        self.assertIn(f'href="{reverse("my_vehicles")}"', body)
        self.assertIn(f'href="{reverse("appointments")}"', body)
        self.assertIn(f'href="{reverse("service_requests")}"', body)
        self.assertIn(f'href="{reverse("vehicles")}"', body)
