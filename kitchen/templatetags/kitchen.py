from django import template
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def prose(text):
    """Plain text to HTML: blank lines split paragraphs, and lines starting with "- " become a bulleted list."""
    blocks = []
    for block in (text or '').replace('\r\n', '\n').split('\n\n'):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue
        if all(line.startswith('- ') for line in lines):
            blocks.append(format_html('<ul>{}</ul>', format_html_join('', '<li>{}</li>', ((l[2:],) for l in lines))))
        else:
            blocks.append(format_html('<p>{}</p>', format_html_join(mark_safe('<br>'), '{}', ((l,) for l in lines))))
    return mark_safe(''.join(blocks))
