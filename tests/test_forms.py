from django.test import TestCase

from two_factor.forms import AuthenticationTokenForm, MethodForm, TOTPDeviceForm
from two_factor.plugins.registry import GeneratorMethod

from .utils import UserMixin


class FormTests(TestCase):
    def test_auth_token_form(self):
        form = AuthenticationTokenForm(None, None, data={'otp_token': '005428'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['otp_token'], '005428')


class TOTPDeviceFormSaveTests(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()

    def _form(self):
        return TOTPDeviceForm(key='1234567890abcdef', user=self.user)

    def test_defaults_to_default_name(self):
        self.assertEqual(self._form().save().name, 'default')

    def test_saves_with_given_name(self):
        self.assertEqual(self._form().save(name='sms').name, 'sms')


class MethodFormTests(TestCase):
    def test_choices_default_to_registry(self):
        form = MethodForm()
        self.assertTrue(form.fields['method'].choices)

    def test_choices_limited_to_given_methods(self):
        form = MethodForm(methods=[GeneratorMethod()])
        self.assertEqual(
            [code for code, _ in form.fields['method'].choices], ['generator'])
