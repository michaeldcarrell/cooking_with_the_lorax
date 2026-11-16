"""Dish photos, shopping lists and menu emails."""
import io
import logging
from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from kitchen.models import DishPhoto, Menu, ShoppingItem, SiteSettings
from kitchen.quantities import format_amount, normalize_name, normalize_unit

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_SIDE = 1800  # big enough for a full-width menu photo; phone photos are far larger


class PhotoError(ValueError):
    """An upload we can't use; the message is shown to the person who uploaded it."""


def save_photo(upload, user, caption: str = '', recipe=None) -> DishPhoto:
    """Store a dish photo as an upright JPEG no bigger than MAX_SIDE, with its metadata (including
    any location) dropped."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise PhotoError(f'{upload.name} is too big (25 MB at most).')
    try:
        image = ImageOps.exif_transpose(Image.open(upload)).convert('RGB')
    except (UnidentifiedImageError, OSError):
        raise PhotoError(f'{upload.name} isn\'t a photo we can read. Try a JPEG or PNG.')
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=85, optimize=True, progressive=True)
    photo = DishPhoto.objects.create(
        image=out.getvalue(), content_type='image/jpeg', width=image.width, height=image.height,
        caption=caption[:200], recipe=recipe, uploaded_by=user)
    if recipe and not recipe.photo_id:
        recipe.photo = photo
        recipe.save(update_fields=['photo'])
    return photo


# --- shopping lists -----------------------------------------------------------------------------------

def _shopping_lines(menu: Menu) -> list[dict]:
    """Every ingredient the menu needs, scaled to each dish's servings and added up across dishes."""
    lines: OrderedDict[tuple[str, str], dict] = OrderedDict()
    items = menu.items.select_related('recipe').prefetch_related('recipe__ingredients')
    for item in items:
        if not item.recipe:
            continue
        factor = item.scale()
        for ing in item.recipe.ingredients.all():
            key = (normalize_name(ing.name), normalize_unit(ing.unit))
            line = lines.setdefault(key, {
                'name': ing.name.strip(), 'unit': ing.unit.strip(), 'section': ing.section,
                'low': Decimal(0), 'high': Decimal(0), 'counted': False, 'unmeasured': False, 'used_in': [],
            })
            if ing.quantity is None:
                line['unmeasured'] = True
            else:
                line['counted'] = True
                line['low'] += ing.quantity * factor
                line['high'] += (ing.quantity_max or ing.quantity) * factor
            title = item.recipe.title
            if title not in line['used_in']:
                line['used_in'].append(title)
    result = []
    for line in lines.values():
        amount = ''
        if line['counted']:
            amount = format_amount(line['low'])
            if line['high'] != line['low']:
                amount += f'–{format_amount(line["high"])}'
            if line['unit']:
                amount += f' {line["unit"]}'
            if line['unmeasured']:
                amount += ' + more'
        elif line['unmeasured']:
            amount = 'as needed'
        result.append({'name': line['name'], 'section': line['section'], 'amount': amount,
                       'used_in': ', '.join(line['used_in'])[:500]})
    return result


@transaction.atomic
def rebuild_shopping_list(menu: Menu) -> int:
    """Recompute the recipe lines of a menu's shopping list. Hand-added lines stay, and lines that
    were already checked off stay checked. Returns the number of recipe lines."""
    checked = {normalize_name(name) for name in
               menu.shopping_items.filter(checked=True, manual=False).values_list('name', flat=True)}
    menu.shopping_items.filter(manual=False).delete()
    lines = _shopping_lines(menu)
    ShoppingItem.objects.bulk_create([
        ShoppingItem(menu=menu, manual=False, checked=normalize_name(line['name']) in checked, **line)
        for line in lines
    ])
    return len(lines)


# --- menu emails --------------------------------------------------------------------------------------

def send_menu(menu: Menu, recipients: list[str]) -> int:
    """Email the menu to `recipients`, each as their own message. Returns how many were sent."""
    site = SiteSettings.load()
    context = {
        'menu': menu,
        'items': menu.items.select_related('recipe__photo', 'photo'),
        'site': site,
        'menu_url': menu.client_url(),
    }
    subject = f'Your menu from {site.chef_name}: {menu.title}'
    text = render_to_string('email/menu.txt', context)
    html = render_to_string('email/menu.html', context)
    sent = 0
    for address in recipients:
        message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [address],
                                         reply_to=[site.contact_email or settings.MENU_REPLY_TO])
        message.attach_alternative(html, 'text/html')
        message.send()
        sent += 1
    menu.sent_at = timezone.now()
    if menu.status == 'draft':
        menu.status = 'sent'
    menu.save(update_fields=['sent_at', 'status'])
    return sent
