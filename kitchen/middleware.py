from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponsePermanentRedirect
from django.http.request import split_domain_port
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

from kitchen.models import AllowedUser

PUBLIC_URLCONF = 'lorax.urls_public'
CHEF_URLCONF = 'lorax.urls'

# Workspace paths anyone can open: sign-in, static files, and the client-facing pages (unguessable links).
PUBLIC_PREFIXES = ('/accounts/', '/static/', '/m/', '/h/', '/photo/', '/favicon.ico', '/healthz', '/robots.txt')


class HostRoutingMiddleware:
    """One app, two hostnames.

    The public host (PUBLIC_BASE_URL) gets the customer-facing website plus the client menu/photo links.
    Every other host gets Lori's workspace, kept out of search engines. A workspace path opened on the
    public host (an old bookmark, say) redirects to the same path on the workspace host.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host, _ = split_domain_port(request.get_host())
        request.is_public_site = host == settings.PUBLIC_HOST and host != settings.CHEF_HOST
        if not request.is_public_site:
            response = self.get_response(request)
            response.setdefault('X-Robots-Tag', 'noindex, nofollow')
            return response

        request.urlconf = PUBLIC_URLCONF
        try:
            resolve(request.path_info, PUBLIC_URLCONF)
        except Resolver404:
            try:
                resolve(request.path_info, CHEF_URLCONF)
            except Resolver404:
                pass
            else:
                return HttpResponsePermanentRedirect(settings.CHEF_BASE_URL + request.get_full_path())
        return self.get_response(request)


class AllowedUserRequiredMiddleware:
    """Workspace pages need a signed-in user who is still on the allow list. The public site doesn't."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if getattr(request, 'is_public_site', False) or path.startswith(PUBLIC_PREFIXES) or path == '/welcome/':
            return self.get_response(request)
        user = request.user
        if not user.is_authenticated:
            return redirect('signin')
        allowed = AllowedUser.objects.filter(email__iexact=user.email).first()
        if not allowed:
            logout(request)
            return redirect('signin')
        request.allowed_user = allowed
        return self.get_response(request)
