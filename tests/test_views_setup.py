from base64 import b32decode
from binascii import unhexlify
from unittest import mock

from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp

from two_factor.plugins.registry import registry
from two_factor.views import SetupView

from .utils import UserMixin, method_registry


class SetupTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.login_user()

    def test_form(self):
        response = self.client.get(reverse('two_factor:setup'))
        self.assertContains(response, 'Follow the steps in this wizard to '
                                      'enable two-factor')

    def test_reentry_shows_add_method_messaging(self):
        self.enable_otp()
        self.login_user()  # re-login so the session device marks us verified
        response = self.client.get(reverse('two_factor:setup'))
        self.assertContains(response, 'Add an authentication method')

    @method_registry(['generator'])
    def test_redirects_to_profile_when_no_methods_available(self):
        self.enable_otp()
        self.login_user()
        response = self.client.get(reverse('two_factor:setup'))
        self.assertRedirects(response, reverse('two_factor:profile'))

    @method_registry(['generator'])
    def test_setup_only_generator_available(self):
        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'welcome'})

        self.assertContains(response, 'Token:')
        self.assertContains(response, 'autofocus="autofocus"')
        self.assertContains(response, 'inputmode="numeric"')
        self.assertContains(response, 'autocomplete="one-time-code"')
        session = self.client.session
        self.assertIn('django_two_factor-qr_secret_key', session.keys())

        # test if secret key is valid base32 and has the correct number of bytes
        secret_key = response.context_data['secret_key']
        self.assertEqual(len(b32decode(secret_key)), 20)
        self.assertEqual(
            response.context_data['otpauth_url'],
            f'otpauth://totp/testserver%3A%20bouke%40example.com?secret={secret_key}&digits=6&issuer=testserver'
        )
        self.assertEqual(response.context_data['issuer'], 'testserver')
        self.assertEqual(response.context_data['totp_digits'], 6)

        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'generator'})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'token': ['This field is required.']})

        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'generator',
                  'generator-token': '123456'})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'token': ['Entered token is not valid.']})

        key = response.context_data['keys'].get('generator')
        bin_key = unhexlify(key.encode())
        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'generator',
                  'generator-token': totp(bin_key)})
        self.assertRedirects(response, reverse('two_factor:setup_complete'))
        self.assertEqual(1, self.user.totpdevice_set.count())

    @override_settings(TWO_FACTOR_CALL_GATEWAY='two_factor.gateways.fake.Fake',
                       TWO_FACTOR_SMS_GATEWAY='two_factor.gateways.fake.Fake')
    def test_setup_generator_with_multi_method(self):
        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'welcome'})
        self.assertContains(response, 'Method:')

        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'method',
                  'method-method': 'generator'})
        self.assertContains(response, 'Token:')
        session = self.client.session
        self.assertIn('django_two_factor-qr_secret_key', session.keys())

        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'generator'})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'token': ['This field is required.']})

        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'generator',
                  'generator-token': '123456'})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'token': ['Entered token is not valid.']})

        key = response.context_data['keys'].get('generator')
        bin_key = unhexlify(key.encode())
        response = self.client.post(
            reverse('two_factor:setup'),
            data={'setup_view-current_step': 'generator',
                  'generator-token': totp(bin_key)})
        self.assertRedirects(response, reverse('two_factor:setup_complete'))
        self.assertEqual(1, self.user.totpdevice_set.count())

    @method_registry(['generator'])
    def test_setup_custom_success_url(self):
        custom_setup = reverse('setup-backup_tokens-redirect')
        custom_redirect = reverse('two_factor:backup_tokens')
        response = self.client.post(
            custom_setup,
            data={
                'setup_view-current_step': 'method',
                'method-method': 'generator'
            }
        )
        key = response.context_data['keys'].get('generator')
        data = {
            'setup_view-current_step': 'generator',
            'generator-token': totp(unhexlify(key.encode()))
        }
        response = self.client.post(custom_setup, data=data)
        self.assertRedirects(response, custom_redirect)

    def _post(self, data):
        return self.client.post(reverse('two_factor:setup'), data=data)

    def test_no_phone(self):
        with self.settings(TWO_FACTOR_CALL_GATEWAY=None):
            response = self._post(data={'setup_view-current_step': 'welcome'})
            self.assertNotContains(response, 'call')

        with self.settings(TWO_FACTOR_CALL_GATEWAY='two_factor.gateways.fake.Fake'):
            response = self._post(data={'setup_view-current_step': 'welcome'})
            self.assertContains(response, 'call')

    @mock.patch('two_factor.gateways.fake.Fake')
    @override_settings(TWO_FACTOR_CALL_GATEWAY='two_factor.gateways.fake.Fake')
    def test_setup_phone_call(self, fake):
        response = self._post(data={'setup_view-current_step': 'welcome'})
        self.assertContains(response, 'Method:')

        response = self._post(data={'setup_view-current_step': 'method',
                                    'method-method': 'call'})
        self.assertContains(response, 'Number:')

        response = self._post(data={'setup_view-current_step': 'call',
                                    'call-number': '+31101234567'})
        self.assertContains(response, 'Token:')
        self.assertContains(response, 'We are calling your phone right now')

        # assert that the token was send to the gateway
        self.assertEqual(
            fake.return_value.method_calls,
            [mock.call.make_call(device=mock.ANY, token=mock.ANY)]
        )

        # assert that tokens are verified
        response = self._post(data={'setup_view-current_step': 'validation',
                                    'validation-token': '666'})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'token': ['Entered token is not valid.']})

        # submitting correct token should finish the setup
        token = fake.return_value.make_call.call_args[1]['token']
        response = self._post(data={'setup_view-current_step': 'validation',
                                    'validation-token': token})
        self.assertRedirects(response, reverse('two_factor:setup_complete'))

        phones = self.user.phonedevice_set.all()
        self.assertEqual(len(phones), 1)
        self.assertEqual(phones[0].name, 'default')
        self.assertEqual(phones[0].number.as_e164, '+31101234567')
        self.assertEqual(phones[0].method, 'call')

    @mock.patch('two_factor.gateways.fake.Fake')
    @override_settings(TWO_FACTOR_SMS_GATEWAY='two_factor.gateways.fake.Fake')
    def test_setup_phone_sms(self, fake):
        response = self._post(data={'setup_view-current_step': 'welcome'})
        self.assertContains(response, 'Method:')

        response = self._post(data={'setup_view-current_step': 'method',
                                    'method-method': 'sms'})
        self.assertContains(response, 'Number:')

        response = self._post(data={'setup_view-current_step': 'sms',
                                    'sms-number': '+31101234567'})
        self.assertContains(response, 'Token:')
        self.assertContains(response, 'We sent you a text message')

        # assert that the token was send to the gateway
        self.assertEqual(
            fake.return_value.method_calls,
            [mock.call.send_sms(device=mock.ANY, token=mock.ANY)]
        )

        # assert that tokens are verified
        response = self._post(data={'setup_view-current_step': 'validation',
                                    'validation-token': '666'})
        self.assertEqual(response.context_data['wizard']['form'].errors,
                         {'token': ['Entered token is not valid.']})

        # submitting correct token should finish the setup
        token = fake.return_value.send_sms.call_args[1]['token']
        response = self._post(data={'setup_view-current_step': 'validation',
                                    'validation-token': token})
        self.assertRedirects(response, reverse('two_factor:setup_complete'))

        phones = self.user.phonedevice_set.all()
        self.assertEqual(len(phones), 1)
        self.assertEqual(phones[0].name, 'default')
        self.assertEqual(phones[0].number.as_e164, '+31101234567')
        self.assertEqual(phones[0].method, 'sms')

    def test_reentry_allowed_when_already_configured(self):
        # A configured user can re-enter the wizard to add another method.
        self.enable_otp()
        self.login_user()
        response = self.client.get(reverse('two_factor:setup'))
        self.assertEqual(response.status_code, 200)

    def test_reentry_blocked_when_configured_but_unverified(self):
        self.enable_otp()
        response = self.client.get(reverse('two_factor:setup'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.login_url, response.url)

    def test_no_double_login(self):
        """
        Activating two-factor authentication for ones account, should
        automatically mark the session as being OTP verified. Refs #44.
        """
        self.test_setup_only_generator_available()
        device = self.user.totpdevice_set.all()[0]

        self.assertEqual(device.persistent_id,
                         self.client.session.get(DEVICE_ID_SESSION_KEY))

    def test_suggest_backup_number(self):
        """
        Finishing the setup wizard should suggest to add a phone number, if
        a phone method is available. Refs #49.
        """
        self.enable_otp()
        self.login_user()

        with self.settings(TWO_FACTOR_SMS_GATEWAY=None):
            response = self.client.get(reverse('two_factor:setup_complete'))
            self.assertNotContains(response, 'Add Phone Number')

        with self.settings(TWO_FACTOR_SMS_GATEWAY='two_factor.gateways.fake.Fake'):
            response = self.client.get(reverse('two_factor:setup_complete'))
            self.assertContains(response, 'Add Phone Number')

    def test_missing_management_data(self):
        # missing management data
        response = self._post({'validation-token': '666'})

        # view should return HTTP 400 Bad Request
        self.assertEqual(response.status_code, 400)


class SetupViewDeviceNameTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.view = SetupView()
        self.view.request = RequestFactory().get('/')
        self.view.request.user = self.user

    def test_first_device_is_named_default(self):
        method = registry.get_method('generator')
        self.assertEqual(self.view.get_new_device_name(method), 'default')

    def test_additional_device_is_named_after_its_method(self):
        self.user.totpdevice_set.create(name='default')
        method = registry.get_method('email')
        self.assertEqual(self.view.get_new_device_name(method), 'email')

    def test_duplicate_method_is_named_after_its_method(self):
        # A second device of an already-configured method is allowed.
        self.user.totpdevice_set.create(name='default')
        method = registry.get_method('generator')
        self.assertEqual(self.view.get_new_device_name(method), 'generator')

    def test_resaving_current_default_keeps_default_name(self):
        # Email reuses and re-saves its own device mid-wizard; the device being
        # saved is excluded, so it stays 'default' instead of being demoted.
        device = self.user.totpdevice_set.create(name='default')
        method = registry.get_method('generator')
        self.assertEqual(self.view.get_new_device_name(method, device), 'default')


class SetupViewAvailableMethodsTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.view = SetupView()
        self.view.request = RequestFactory().get('/')
        self.view.request.user = self.user
        self.view.storage = mock.Mock(validated_step_data={})

    def codes(self):
        return [method.code for method in self.view.get_available_methods()]

    @method_registry(['generator', 'webauthn'])
    def test_lists_all_when_none_configured(self):
        self.assertEqual(set(self.codes()), {'generator', 'webauthn'})

    @method_registry(['generator', 'webauthn'])
    def test_excludes_configured_single_method(self):
        self.user.totpdevice_set.create(name='default')
        self.assertEqual(self.codes(), ['webauthn'])

    @method_registry(['generator', 'webauthn'])
    def test_keeps_webauthn_when_already_configured(self):
        self.user.webauthn_keys.create(
            name='default', public_key='x', key_handle='y', sign_count=0)
        self.assertIn('webauthn', self.codes())

    @method_registry(['generator', 'webauthn'])
    def test_keeps_current_method_being_set_up(self):
        # A single method stays available while it is the one being set up, even
        # though its device may have been saved mid-wizard (e.g. email).
        self.user.totpdevice_set.create(name='default')
        self.view.get_method = lambda: registry.get_method('generator')
        self.assertIn('generator', self.codes())
