from unittest import mock, skipUnless

from django.test import TestCase
from django.urls import reverse

from tests.utils import UserMixin

try:
    import webauthn
except ImportError:
    webauthn = None


class SetupTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.login_user()

    def _setup(self, **data):
        return self.client.post(reverse('two_factor:setup'), data=data)

    def _mock_credential(self):
        # The wizard re-validates the credential form when done() runs on the
        # final step, so the mock must stay active through the nickname step.
        parse = mock.patch(
            "two_factor.plugins.webauthn.forms.parse_registration_credential_json")
        verify = mock.patch(
            "two_factor.plugins.webauthn.method.verify_registration_response")
        ctx = parse.__enter__()
        verify.__enter__().return_value = (
            'mocked_public_key', 'mocked_credential_id', 0)
        self.addCleanup(parse.__exit__, None, None, None)
        self.addCleanup(verify.__exit__, None, None, None)
        return ctx

    def _collect_credential(self):
        """welcome → method → credential ceremony (nickname step comes next)."""
        self._setup(**{'setup_view-current_step': 'welcome'})
        self._setup(**{'setup_view-current_step': 'method', 'method-method': 'webauthn'})
        self._mock_credential()
        return self._setup(**{'setup_view-current_step': 'webauthn',
                              'webauthn-token': 'a_valid_token'})

    def _register_webauthn(self, nickname='My passkey'):
        """Drive the wizard through welcome → method → credential → nickname."""
        self._collect_credential()
        return self._setup(**{'setup_view-current_step': 'webauthn_nickname',
                              'webauthn_nickname-nickname': nickname})

    @skipUnless(webauthn, 'package webauthn is not present')
    def test_setup_webauthn_stores_nickname(self):
        self.assertEqual(0, self.user.webauthn_keys.count())
        response = self._register_webauthn(nickname='Work laptop')
        self.assertRedirects(response, reverse('two_factor:setup_complete'))
        device = self.user.webauthn_keys.get()
        self.assertEqual(device.nickname, 'Work laptop')

    @skipUnless(webauthn, 'package webauthn is not present')
    def test_nickname_is_required(self):
        self._collect_credential()
        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'webauthn_nickname',
                  'webauthn_nickname-nickname': ''})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'nickname': ['This field is required.']})
        self.assertEqual(0, self.user.webauthn_keys.count())

    @skipUnless(webauthn, 'package webauthn is not present')
    def test_setup_second_webauthn(self):
        self.user.webauthn_keys.create(
            name='default', public_key='x', key_handle='AAAA', sign_count=0)
        self.login_user()
        self._register_webauthn(nickname='Phone')
        self.assertEqual(2, self.user.webauthn_keys.count())
        self.assertTrue(self.user.webauthn_keys.filter(nickname='Phone').exists())
