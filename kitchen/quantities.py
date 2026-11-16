"""Kitchen quantities: parse "1 1/2" / "½" / "2-3", print scaled amounts as cooks write them, and
normalize units so a shopping list can add up the same ingredient from different recipes."""
import re
from decimal import Decimal, InvalidOperation

UNICODE_FRACTIONS = {
    '¼': '1/4', '½': '1/2', '¾': '3/4', '⅓': '1/3', '⅔': '2/3', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8',
    '⅕': '1/5', '⅖': '2/5', '⅗': '3/5', '⅘': '4/5', '⅙': '1/6', '⅚': '5/6',
}
# Fractions we print, by value. Thirds included because recipes use them.
NICE_FRACTIONS = [
    (Decimal(1) / 8, '⅛'), (Decimal(1) / 4, '¼'), (Decimal(1) / 3, '⅓'), (Decimal(3) / 8, '⅜'),
    (Decimal(1) / 2, '½'), (Decimal(5) / 8, '⅝'), (Decimal(2) / 3, '⅔'), (Decimal(3) / 4, '¾'),
    (Decimal(7) / 8, '⅞'),
]

_NUMBER = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|\.\d+)'
_RANGE_RE = re.compile(rf'^\s*({_NUMBER})\s*(?:-|–|—|to)\s*({_NUMBER})\s*$')


def _expand_unicode(text: str) -> str:
    for char, plain in UNICODE_FRACTIONS.items():
        # "1½" -> "1 1/2"
        text = re.sub(rf'(\d){char}', rf'\1 {plain}', text).replace(char, plain)
    return text


def _number(text: str) -> Decimal:
    text = text.strip()
    if ' ' in text:
        whole, frac = text.split(None, 1)
        return Decimal(whole) + _number(frac)
    if '/' in text:
        num, den = text.split('/', 1)
        return Decimal(num) / Decimal(den)
    return Decimal(text)


def parse_amount(text: str) -> tuple[Decimal | None, Decimal | None]:
    """'1 1/2' -> (1.5, None); '2-3' -> (2, 3); '' or 'to taste' -> (None, None).

    Raises ValueError for text that looks numeric but isn't (e.g. '1//2').
    """
    text = _expand_unicode((text or '').strip())
    if not text:
        return None, None
    try:
        match = _RANGE_RE.match(text)
        if match:
            return _quant(_number(match.group(1))), _quant(_number(match.group(2)))
        if re.fullmatch(_NUMBER, text):
            return _quant(_number(text)), None
    except (InvalidOperation, ZeroDivisionError):
        pass
    raise ValueError(f'"{text}" isn\'t an amount. Use numbers like 2, 1.5, 1 1/2 or 2-3.')


def _quant(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.001'))


def format_amount(value: Decimal | float | None) -> str:
    """1.5 -> '1 ½', 0.333 -> '⅓', 2 -> '2', 37.5 -> '38'. Amounts are rounded to what a cook would measure."""
    if value is None:
        return ''
    value = Decimal(str(value))
    if value <= 0:
        return '0'
    if value >= 20:
        return str(int(value.to_integral_value()))
    whole = int(value)
    frac = value - whole
    best_text, best_err = '', frac  # rounding down to the whole number
    for amount, glyph in NICE_FRACTIONS:
        err = abs(frac - amount)
        if err < best_err:
            best_text, best_err = glyph, err
    if abs(1 - frac) < best_err:
        whole, best_text = whole + 1, ''
    if whole and best_text:
        return f'{whole} {best_text}'
    if best_text:
        return best_text
    return str(whole) if whole else '⅛'  # never print 0 for a real amount


UNIT_ALIASES = {
    'tsp': ['t', 'tsp', 'tsps', 'teaspoon', 'teaspoons'],
    'tbsp': ['T', 'tbsp', 'tbsps', 'tbs', 'tbl', 'tablespoon', 'tablespoons'],
    'cup': ['c', 'cup', 'cups'],
    'oz': ['oz', 'ounce', 'ounces'],
    'fl oz': ['fl oz', 'fluid ounce', 'fluid ounces'],
    'lb': ['lb', 'lbs', 'pound', 'pounds'],
    'g': ['g', 'gram', 'grams'],
    'kg': ['kg', 'kilogram', 'kilograms'],
    'ml': ['ml', 'milliliter', 'milliliters', 'millilitre', 'millilitres'],
    'l': ['l', 'liter', 'liters', 'litre', 'litres'],
    'pint': ['pt', 'pint', 'pints'],
    'quart': ['qt', 'quart', 'quarts'],
    'clove': ['clove', 'cloves'],
    'can': ['can', 'cans'],
    'bunch': ['bunch', 'bunches'],
    'pinch': ['pinch', 'pinches'],
    'slice': ['slice', 'slices'],
    'stick': ['stick', 'sticks'],
    'sprig': ['sprig', 'sprigs'],
    'head': ['head', 'heads'],
    'package': ['package', 'packages', 'pkg', 'pkgs'],
}
_UNIT_LOOKUP = {}
for canonical, aliases in UNIT_ALIASES.items():
    for alias in aliases:
        # "T" (tablespoon) and "t" (teaspoon) differ only by case; everything else is case-insensitive.
        _UNIT_LOOKUP[alias if alias in ('T', 't') else alias.lower()] = canonical


def normalize_unit(unit: str) -> str:
    unit = (unit or '').strip().rstrip('.')
    if unit in ('T', 't'):
        return _UNIT_LOOKUP[unit]
    return _UNIT_LOOKUP.get(unit.lower(), unit.lower())


def normalize_name(name: str) -> str:
    """'Yellow Onions' -> 'yellow onion', for matching the same ingredient across recipes."""
    name = re.sub(r'\s+', ' ', (name or '').strip().lower())
    if len(name) > 3 and name.endswith('es') and name[-3] in 'sxz' or name.endswith(('oes', 'ches', 'shes')):
        return name[:-2]
    if len(name) > 3 and name.endswith('s') and not name.endswith(('ss', 'us', 'is')):
        return name[:-1]
    return name
