from django.contrib.auth import logout
from django.shortcuts import redirect

from kitchen.models import AllowedUser

# Paths anyone can open: sign-in, static files, and the client-facing pages (unguessable links).
PUBLIC_PREFIXES = ('/accounts/', '/static/', '/m/', '/h/', '/photo/', '/favicon.ico', '/healthz')


class AllowedUserRequiredMiddleware:
    """Everything except the public pages needs a signed-in user who is still on the allow list."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith(PUBLIC_PREFIXES) or path == '/welcome/':
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
