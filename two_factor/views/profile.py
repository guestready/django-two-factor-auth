from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, resolve_url
from django.utils.functional import lazy
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView, View
from django_otp import devices_for_user
from django_otp.decorators import otp_required
from django_otp import DEVICE_ID_SESSION_KEY
import django_otp

from two_factor.plugins.phonenumber.utils import (
    backup_phones, get_available_phone_methods,
)

from ..forms import DisableForm
from ..plugins.registry import registry
from ..utils import (
    default_device, get_method_devices, other_method_devices,
    reset_default_device_cache, resolve_user_device,
)
from .utils import class_view_decorator


@class_view_decorator(never_cache)
@class_view_decorator(login_required)
class ProfileView(TemplateView):
    """
    View used by users for managing two-factor configuration.

    This view shows whether two-factor has been configured for the user's
    account. If two-factor is enabled, it also lists the primary verification
    method and backup verification methods.
    """
    template_name = 'two_factor/profile/profile.html'

    def get_context_data(self, **kwargs):
        user = self.request.user

        try:
            backup_tokens = user.staticdevice_set.all()[0].token_set.count()

        except Exception:
            backup_tokens = 0

        context = {
            'default_device': default_device(user),
            'default_device_type': default_device(user).__class__.__name__,
            'backup_tokens': backup_tokens,
            'backup_phones': backup_phones(user),
            'available_phone_methods': get_available_phone_methods(),
            'method_devices': get_method_devices(user),
        }

        return context


@class_view_decorator(never_cache)
class DisableView(FormView):
    """
    View for disabling two-factor for a user's account.
    """
    template_name = 'two_factor/profile/disable.html'
    success_url = lazy(resolve_url, str)(settings.LOGIN_REDIRECT_URL)
    form_class = DisableForm

    def dispatch(self, *args, **kwargs):
        # We call otp_required here because we want to use self.success_url as
        # the login_url. Using it as a class decorator would make it difficult
        # for users who wish to override this property
        fn = otp_required(super().dispatch, login_url=self.success_url, redirect_field_name=None)
        return fn(*args, **kwargs)

    def form_valid(self, form):
        for device in devices_for_user(self.request.user):
            device.delete()
        return redirect(self.success_url)


@class_view_decorator(never_cache)
@class_view_decorator(otp_required)
class DeviceSetDefaultView(View):
    """Make a configured method device the primary one."""
    http_method_names = ['post']
    success_url = 'two_factor:profile'

    def post(self, request, *args, **kwargs):
        device = resolve_user_device(request.user, request.POST.get('device'))
        if device.name != 'default':
            current = default_device(request.user)
            with transaction.atomic():
                if current:
                    current.name = registry.method_from_device(current).code
                    current.save(update_fields=['name'])
                device.name = 'default'
                device.save(update_fields=['name'])
            reset_default_device_cache(request.user)
        return redirect(resolve_url(self.success_url))


@class_view_decorator(never_cache)
@class_view_decorator(otp_required)
class DeviceDeleteView(View):
    """Remove a method device; the last one hands off to DisableView."""
    http_method_names = ['post']
    success_url = 'two_factor:profile'

    def post(self, request, *args, **kwargs):
        device = resolve_user_device(request.user, request.POST.get('device'))
        others = other_method_devices(request.user, device)
        if not others:
            return redirect('two_factor:disable')
        verified_with_deleted = request.session.get(DEVICE_ID_SESSION_KEY) == device.persistent_id
        with transaction.atomic():
            was_default = device.name == 'default'
            device.delete()
            if was_default:
                others[0].name = 'default'
                others[0].save(update_fields=['name'])
        reset_default_device_cache(request.user)
        if verified_with_deleted:
            django_otp.login(request, default_device(request.user)) # promote the new default
        return redirect(resolve_url(self.success_url))
