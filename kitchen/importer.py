"""Recipe importer: turns a web page, photos (a cookbook page, a handwritten card) or pasted text into a
structured recipe with Claude, then saves it for Lori to review.

Web pages are fetched here first, so Claude reads the page's own recipe data (most recipe sites embed
schema.org JSON-LD). If a site refuses our request, Claude fetches it with its web fetch tool instead.
"""
import base64
import io
import ipaddress
import json
import logging
import socket
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse

import anthropic
import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from kitchen.models import SECTION_KEYS, Ingredient, Recipe, Step

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_PAGE_CHARS = 120_000
MAX_IMAGES = 6
MAX_IMAGE_SIDE = 2000  # plenty to read a cookbook page; keeps each image well under the API's size limit
USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/131.0 Safari/537.36')

SYSTEM_PROMPT = f"""You turn recipes into structured data for a private chef's recipe box.

Transcribe the recipe faithfully: keep the author's ingredients, amounts and method. Don't invent \
ingredients, amounts or steps that aren't there, and don't "improve" the recipe. Fix obvious OCR or \
typing errors only.

Ingredients:
- `quantity` is a number (1.5 for "1 1/2", 0.25 for "¼"), or null when there is none ("salt to taste"). \
For a range like "2-3 cloves", `quantity` is 2 and `quantity_max` is 3; otherwise `quantity_max` is null.
- `unit` is the measure as written, singular or plural ("cup", "tbsp", "cloves", "can (15 oz)"), or "" \
for counted items ("2 eggs").
- `name` is the ingredient itself ("yellow onion", "unsalted butter"); prep goes in `note` \
("finely diced", "softened", "divided").
- `section` is the grocery store section to shop for it in: one of {", ".join(SECTION_KEYS)}.
- Keep sub-recipe groups ("For the sauce") by putting the group name in each ingredient's note only \
if the recipe uses the same ingredient twice; otherwise list ingredients in order.

Steps are the method in order, one step per entry, without leading numbers.
`description` is one or two appetizing sentences a client could read on a menu. Use the recipe's own \
headnote if it has one; otherwise write one from the dish.
Times are minutes, or null when the source doesn't say. `servings` is the number of people it serves \
(use the low end of a range; estimate from the amounts if not stated).

If the input doesn't contain a recipe, set `found` to false and explain why in `problem`."""


Section = Literal['produce', 'meat', 'dairy', 'bakery', 'pantry', 'spices', 'frozen', 'other']


class IngredientDraft(BaseModel):
    quantity: float | None
    quantity_max: float | None
    unit: str
    name: str
    note: str
    section: Section


class RecipeDraft(BaseModel):
    found: bool
    problem: str = Field(description='Why no recipe could be read, when found is false; otherwise "".')
    title: str
    description: str
    servings: int
    prep_minutes: int | None
    cook_minutes: int | None
    tags: list[str] = Field(description='A few short tags: meal type, main ingredient, diet (e.g. "vegetarian").')
    ingredients: list[IngredientDraft]
    steps: list[str]


class ImportError_(Exception):
    """The import couldn't produce a recipe; the message is shown to Lori."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _ask(content: list[dict], tools: list[dict] | None = None) -> RecipeDraft:
    messages = [{'role': 'user', 'content': content}]
    kwargs = {'tools': tools} if tools else {}
    try:
        for _ in range(4):  # a server tool (web fetch) can pause the turn; continue it a few times
            response = _client().beta.messages.parse(
                model=settings.CLAUDE_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=messages,
                output_format=RecipeDraft,
                output_config={'effort': 'medium'},
                # On a safety decline, let the API retry on a fallback model instead of failing the import.
                betas=['server-side-fallback-2026-07-01'],
                fallbacks='default',
                **kwargs,
            )
            if response.stop_reason != 'pause_turn':
                break
            messages = [*messages, {'role': 'assistant', 'content': response.content}]
    except anthropic.RateLimitError:
        raise ImportError_('The recipe reader is busy right now. Try again in a minute.')
    except anthropic.APIConnectionError:
        raise ImportError_('Couldn\'t reach the recipe reader. Check the connection and try again.')
    except anthropic.APIStatusError as e:
        logger.exception('Claude import failed')
        raise ImportError_(f'The recipe reader returned an error ({e.status_code}). Try again, or add it by hand.')

    logger.info('import usage: %s', response.usage)
    if response.stop_reason == 'refusal':
        raise ImportError_('The recipe reader declined this one. Try a different source, or add it by hand.')
    if response.stop_reason == 'max_tokens' or response.parsed_output is None:
        raise ImportError_('The recipe was too long to read in one go. Try pasting it in parts, or add it by hand.')
    draft = response.parsed_output
    if not draft.found:
        raise ImportError_(draft.problem or 'No recipe found there.')
    if not draft.ingredients and not draft.steps:
        raise ImportError_('Found a title but no ingredients or steps. Try another source, or add it by hand.')
    return draft


# --- web pages ----------------------------------------------------------------------------------------

def check_url(url: str) -> str:
    """Only public http(s) pages; never something on the home network."""
    url = (url or '').strip()
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ImportError_('Enter a full web address starting with https://')
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror:
        raise ImportError_(f'Couldn\'t find the site {parsed.hostname}. Check the address.')
    for address in addresses:
        ip = ipaddress.ip_address(address.split('%')[0])
        if not ip.is_global:
            raise ImportError_('That address isn\'t a public website.')
    return url


def _fetch_page(url: str) -> str | None:
    """The page's HTML, or None if the site won't serve it to us."""
    try:
        for _ in range(6):
            # Redirects are followed by hand so every hop is checked before it's requested: a public page
            # mustn't be able to bounce the server onto the home network.
            with requests.get(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'},
                              timeout=20, stream=True, allow_redirects=False) as response:
                if response.is_redirect:
                    url = check_url(requests.compat.urljoin(url, response.headers['Location']))
                    continue
                if not response.ok:
                    logger.info('Fetching %s returned HTTP %s', url, response.status_code)
                    return None
                body = response.raw.read(MAX_PAGE_BYTES, decode_content=True)
                return body.decode(response.encoding or 'utf-8', errors='replace')
        logger.info('Too many redirects fetching %s', url)
        return None
    except requests.RequestException as e:
        logger.info('Fetching %s failed: %s', url, e)
        return None


def page_text(html: str) -> str:
    """The parts of a page that describe its recipe: schema.org Recipe data plus the readable text."""
    soup = BeautifulSoup(html, 'html.parser')
    structured = []
    for script in soup.find_all('script', type='application/ld+json'):
        raw = script.string or script.get_text()
        if raw and 'Recipe' in raw:
            try:
                structured.append(json.dumps(json.loads(raw), ensure_ascii=False))
            except ValueError:
                structured.append(raw.strip())
    for tag in soup(['script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header', 'form', 'iframe']):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ''
    text = '\n'.join(line for line in (l.strip() for l in soup.get_text('\n').splitlines()) if line)
    parts = [f'Page title: {title}']
    if structured:
        parts.append('Structured recipe data on the page:\n' + '\n'.join(structured))
    parts.append('Page text:\n' + text)
    return '\n\n'.join(parts)[:MAX_PAGE_CHARS]


def from_url(url: str) -> RecipeDraft:
    url = check_url(url)
    html = _fetch_page(url)
    if html:
        return _ask([{'type': 'text', 'text': f'Source: {url}\n\n<page>\n{page_text(html)}\n</page>\n\n'
                                              'Extract the recipe from this page.'}])
    # The site blocked us; let Claude fetch it.
    return _ask(
        [{'type': 'text', 'text': f'Fetch {url} and extract the recipe from it.'}],
        tools=[{'type': 'web_fetch_20260209', 'name': 'web_fetch', 'max_uses': 3}],
    )


# --- photos and text ----------------------------------------------------------------------------------

def _image_block(upload) -> dict:
    try:
        image = ImageOps.exif_transpose(Image.open(upload)).convert('RGB')
    except (UnidentifiedImageError, OSError):
        raise ImportError_(f'{upload.name} isn\'t a photo we can read. Use JPEG, PNG, HEIC-converted, or WebP.')
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    image.save(out, 'JPEG', quality=88)
    return {'type': 'image',
            'source': {'type': 'base64', 'media_type': 'image/jpeg',
                       'data': base64.standard_b64encode(out.getvalue()).decode('ascii')}}


def from_photos(uploads) -> RecipeDraft:
    uploads = list(uploads)
    if not uploads:
        raise ImportError_('Choose at least one photo.')
    if len(uploads) > MAX_IMAGES:
        raise ImportError_(f'Up to {MAX_IMAGES} photos per recipe.')
    content = [_image_block(u) for u in uploads]
    content.append({'type': 'text', 'text': 'These photos show one recipe (in order, if there are several pages). '
                                            'Extract it.'})
    return _ask(content)


def from_text(text: str) -> RecipeDraft:
    text = (text or '').strip()
    if not text:
        raise ImportError_('Paste the recipe text first.')
    return _ask([{'type': 'text', 'text': f'<recipe>\n{text}\n</recipe>\n\nExtract this recipe.'}])


# --- saving -------------------------------------------------------------------------------------------

def _decimal(value: float | None) -> Decimal | None:
    if value is None or value < 0:
        return None
    return Decimal(str(round(value, 3)))


@transaction.atomic
def save_draft(draft: RecipeDraft, source_url: str = '', source_note: str = '') -> Recipe:
    recipe = Recipe.objects.create(
        title=draft.title.strip()[:200] or 'Untitled recipe',
        description=draft.description.strip(),
        servings=max(1, draft.servings or 1),
        prep_minutes=draft.prep_minutes if (draft.prep_minutes or 0) > 0 else None,
        cook_minutes=draft.cook_minutes if (draft.cook_minutes or 0) > 0 else None,
        tags=', '.join(t.strip() for t in draft.tags if t.strip())[:300],
        source_url=source_url[:1000],
        source_note=source_note[:200],
    )
    Ingredient.objects.bulk_create([
        Ingredient(recipe=recipe, order=i, quantity=_decimal(ing.quantity), quantity_max=_decimal(ing.quantity_max),
                   unit=ing.unit.strip()[:40], name=ing.name.strip()[:200] or '?', note=ing.note.strip()[:200],
                   section=ing.section)
        for i, ing in enumerate(draft.ingredients)
    ])
    Step.objects.bulk_create([
        Step(recipe=recipe, order=i, text=text.strip()) for i, text in enumerate(draft.steps) if text.strip()
    ])
    return recipe
