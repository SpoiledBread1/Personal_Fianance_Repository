from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse


class SignupTests(TestCase):
	def test_signup_creates_user_and_logs_them_in(self):
		response = self.client.post(
			reverse("finance:signup"),
			{
				"username": "newuser",
				"password1": "C0mpl3x!Passphrase",
				"password2": "C0mpl3x!Passphrase",
			},
		)

		user = get_user_model().objects.get(username="newuser")
		self.assertRedirects(response, reverse("finance:dashboard"))
		self.assertTrue(user.check_password("C0mpl3x!Passphrase"))
		self.assertIn("_auth_user_id", self.client.session)

	def test_signup_rejects_mismatched_passwords(self):
		response = self.client.post(
			reverse("finance:signup"),
			{
				"username": "newuser",
				"password1": "C0mpl3x!Passphrase",
				"password2": "Different!Passphrase",
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertFalse(get_user_model().objects.filter(username="newuser").exists())
