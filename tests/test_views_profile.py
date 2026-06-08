from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from two_factor.plugins.phonenumber.models import PhoneDevice
from two_factor.plugins.registry import registry

from .utils import UserMixin

PHONE_GATEWAYS = override_settings(
    TWO_FACTOR_SMS_GATEWAY='two_factor.gateways.fake.Fake',
    TWO_FACTOR_CALL_GATEWAY='two_factor.gateways.fake.Fake',
)


@override_settings(
    TWO_FACTOR_SMS_GATEWAY='two_factor.gateways.fake.Fake',
    TWO_FACTOR_CALL_GATEWAY='two_factor.gateways.fake.Fake',
)
class ProfileTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.enable_otp()
        self.login_user()

    def get_profile(self):
        url = reverse('two_factor:profile')
        return self.client.get(url)

    def test_get_profile_without_phonenumber_plugin_enabled(self):
        without_phonenumber_plugin = [
            app for app in settings.INSTALLED_APPS if app != 'two_factor.plugins.phonenumber']

        with override_settings(INSTALLED_APPS=without_phonenumber_plugin):
            self.assertFalse(registry.get_method('call'))
            self.assertFalse(registry.get_method('sms'))

            response = self.get_profile()

        self.assertTrue(response.context['available_phone_methods'] == [])

    def test_get_profile_with_phonenumer_plugin_enabled(self):
        self.assertTrue(registry.get_method('call'))
        self.assertTrue(registry.get_method('sms'))

        response = self.get_profile()
        available_phone_method_codes = {method.code for method in response.context['available_phone_methods']}
        self.assertTrue(available_phone_method_codes == {'call', 'sms'})


@PHONE_GATEWAYS
class DeviceSetDefaultViewTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.totp = self.enable_otp()
        self.login_user()
        self.phone = self.user.phonedevice_set.create(
            name='sms', method='sms', number='+12024561111')

    def post(self, device):
        return self.client.post(
            reverse('two_factor:device_set_default'),
            {'device': device.persistent_id})

    def test_swap_makes_device_primary(self):
        response = self.post(self.phone)
        self.assertRedirects(response, reverse('two_factor:profile'))
        self.phone.refresh_from_db()
        self.totp.refresh_from_db()
        self.assertEqual(self.phone.name, 'default')
        self.assertEqual(self.totp.name, 'generator')

    def test_noop_when_already_default(self):
        self.post(self.totp)
        self.totp.refresh_from_db()
        self.assertEqual(self.totp.name, 'default')


@PHONE_GATEWAYS
class DeviceDeleteViewTest(UserMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = self.create_user()
        self.totp = self.enable_otp()
        self.login_user()

    def post(self, device):
        return self.client.post(
            reverse('two_factor:device_delete'),
            {'device': device.persistent_id})

    def add_phone(self):
        return self.user.phonedevice_set.create(
            name='sms', method='sms', number='+12024561111')

    def test_delete_non_default_keeps_primary(self):
        phone = self.add_phone()
        self.post(phone)
        self.assertFalse(PhoneDevice.objects.filter(pk=phone.pk).exists())
        self.assertEqual(self.user.totpdevice_set.get().name, 'default')

    def test_delete_default_promotes_another(self):
        phone = self.add_phone()
        self.post(self.totp)
        self.assertEqual(self.user.totpdevice_set.count(), 0)
        phone.refresh_from_db()
        self.assertEqual(phone.name, 'default')

    def test_delete_last_device_redirects_to_disable(self):
        response = self.post(self.totp)
        self.assertRedirects(response, reverse('two_factor:disable'),
                             fetch_redirect_response=False)
        self.assertEqual(self.user.totpdevice_set.count(), 1)
