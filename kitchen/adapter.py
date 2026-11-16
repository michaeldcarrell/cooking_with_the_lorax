import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth.models import User
from django.http import HttpResponseForbidden
from django.template.loader import render_to_string

from kitchen.models import AllowedUser

logger = logging.getLogger(__name__)


class AllowListSocialAdapter(DefaultSocialAccountAdapter):
    """Google sign-in for the accounts on the AllowedUser list only."""

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        logger.error('Google sign-in error: provider=%s error=%s exception=%r', provider, error, exception)

    def pre_social_login(self, request, sociallogin):
        email = (sociallogin.account.extra_data.get('email') or '').lower()
        allowed = AllowedUser.objects.filter(email__iexact=email).first()
        if not allowed or not sociallogin.account.extra_data.get('email_verified', True):
            logger.warning('Refused sign-in for %s', email or '(no email)')
            raise ImmediateHttpResponse(HttpResponseForbidden(render_to_string('forbidden.html', request=request)))

        user = sociallogin.user
        if not user.id:
            existing = User.objects.filter(email__iexact=email).first()
            if existing:
                sociallogin.connect(request, existing)
                user = existing
            else:
                user.email = email
                user.username = email
                user.first_name = sociallogin.account.extra_data.get('given_name', '')
                sociallogin.save(request)
        sync_admin_flags(user, allowed)


def sync_admin_flags(user, allowed: AllowedUser | None):
    """Admins on the allow list also get Django admin (/django-admin/) for troubleshooting."""
    is_admin = bool(allowed and allowed.is_admin)
    if user.pk and (user.is_staff, user.is_superuser) != (is_admin, is_admin):
        user.is_staff = user.is_superuser = is_admin
        user.save(update_fields=['is_staff', 'is_superuser'])


class ClosedAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False
