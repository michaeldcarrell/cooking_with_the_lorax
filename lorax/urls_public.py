"""The public website (PUBLIC_BASE_URL). See kitchen.middleware.HostRoutingMiddleware."""
from django.urls import path

from kitchen import website_views as w
from lorax.urls_common import common_patterns

urlpatterns = [
    path('', w.home, name='site_home'),
    path('about/', w.about, name='site_about'),
    path('services/', w.services, name='site_services'),
    path('gallery/', w.gallery, name='site_gallery'),
    path('contact/', w.contact, name='site_contact'),
    path('contact/thanks/', w.contact_thanks, name='site_contact_thanks'),
    path('privacy/', w.privacy, name='site_privacy'),
    path('robots.txt', w.robots_txt, name='site_robots'),
    path('sitemap.xml', w.sitemap_xml, name='site_sitemap'),
] + common_patterns
