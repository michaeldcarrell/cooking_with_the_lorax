"""URLs served on both hostnames: client menu/household/photo links (unguessable, no login) and the
health check. Emails link to them on the public host, but links that went out before the split, and
any opened on the workspace host, keep working."""
from django.urls import path

from kitchen import views as v

common_patterns = [
    path('healthz', v.healthz, name='healthz'),
    path('photo/<uuid:token>/', v.photo_file, name='photo_file'),
    path('m/<uuid:token>/', v.client_menu, name='client_menu'),
    path('h/<uuid:token>/', v.client_household, name='client_household'),
]
