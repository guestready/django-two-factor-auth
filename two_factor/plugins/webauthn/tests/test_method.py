from django.test import TestCase

from two_factor.plugins.webauthn.method import WebAuthnMethod
from two_factor.plugins.webauthn.models import WebauthnDevice


class WebAuthnMethodLabelTest(TestCase):
    def _device(self, nickname):
        return WebauthnDevice(
            name='default', nickname=nickname,
            public_key='x', key_handle='y', sign_count=0)

    def test_label_includes_nickname(self):
        label = WebAuthnMethod().get_device_label(self._device('Work laptop'))
        self.assertEqual(label, 'WebAuthn - Work laptop')

    def test_label_without_nickname_is_method_name(self):
        label = WebAuthnMethod().get_device_label(self._device(''))
        self.assertEqual(label, 'WebAuthn')
