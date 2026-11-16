from kitchen.models import MenuFeedback, SiteSettings

NAV_SECTIONS = {
    'home': 'home',
    'households': 'clients', 'household': 'clients', 'household_edit': 'clients', 'household_preferences': 'clients',
    'menu': 'clients', 'menu_shopping': 'clients', 'menu_send': 'clients', 'menu_item_edit': 'clients',
    'recipes': 'recipes', 'recipe': 'recipes', 'recipe_new': 'recipes', 'recipe_edit': 'recipes',
    'photos': 'photos', 'photo_edit': 'photos',
    'manage': 'manage',
}


def ui(request):
    match = request.resolver_match
    context = {'nav_section': NAV_SECTIONS.get(match.url_name if match else None, '')}
    if getattr(request, 'allowed_user', None):
        context['site'] = SiteSettings.load()
        context['unread_feedback'] = MenuFeedback.objects.filter(read=False).count()
        context['is_admin'] = request.allowed_user.is_admin
    return context
