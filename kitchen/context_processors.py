from django.conf import settings

from kitchen.models import Inquiry, MenuFeedback, SiteSettings

NAV_SECTIONS = {
    'home': 'home',
    'households': 'clients', 'household': 'clients', 'household_edit': 'clients', 'household_preferences': 'clients',
    'menu': 'clients', 'menu_shopping': 'clients', 'menu_send': 'clients', 'menu_item_edit': 'clients',
    'recipes': 'recipes', 'recipe': 'recipes', 'recipe_new': 'recipes', 'recipe_edit': 'recipes',
    'meals': 'meals', 'meal': 'meals',
    'photos': 'photos', 'photo_edit': 'photos',
    'website': 'website',
    'manage': 'manage',
}


def ui(request):
    match = request.resolver_match
    if getattr(request, 'is_public_site', False):
        return {'site': SiteSettings.load(), 'page': match.url_name if match else '',
                'public_base_url': settings.PUBLIC_BASE_URL}
    context = {'nav_section': NAV_SECTIONS.get(match.url_name if match else None, '')}
    if getattr(request, 'allowed_user', None):
        context['site'] = SiteSettings.load()
        context['unread_feedback'] = MenuFeedback.objects.filter(read=False).count()
        context['new_inquiries'] = Inquiry.objects.filter(handled=False).count()
        context['is_admin'] = request.allowed_user.is_admin
    return context
