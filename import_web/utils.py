"""
Pure helper functions shared across the `import_web` plugin.

Everything here is standard-library only (no Django, no third-party imports)
except explicitly lazy cookbook imports, so these helpers are safe to use from
per-site adapters, the JSON-LD parser, the scrapers fallback and the view.
"""

import json
import re
from fractions import Fraction
from html import unescape
from urllib.parse import urlparse

# --- regexes -----------------------------------------------------------------

_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)

_NUM = r'(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?|\d+[.,]\d+)'
_AMOUNT_HEAD_RE = re.compile(rf'^\s*{_NUM}\b')

_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')

# ISO 8601 duration, e.g. PT10M, PT1H30M, P1DT2H, PT0M
_DURATION_RE = re.compile(
    r'P(?:(?P<days>\d+)D)?'
    r'(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?'
)


# --- text cleaning -------------------------------------------------------------

def clean(text):
    """Strip HTML tags, unescape entities and collapse whitespace."""
    if text is None:
        return ''
    if not isinstance(text, str):
        text = str(text)
    text = unescape(text)
    text = _TAG_RE.sub(' ', text)
    text = _WS_RE.sub(' ', text).strip()
    return text


def strip_outer_quotes(text):
    """Drop one pair of matching surrounding quotes, if present."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", '\u201c', '\u201d'):
        return text[1:-1].strip()
    return text.strip()


def page_domain(url):
    """Best-effort registrable domain of a URL without external deps
    (strips a single common subdomain prefix such as `www` or `m`)."""
    try:
        host = (urlparse(url or '').hostname or '').lower()
    except (ValueError, AttributeError):
        return ''
    parts = host.split('.')
    if len(parts) >= 3 and parts[0] in ('www', 'm'):
        parts = parts[1:]
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


# --- numbers / servings ------------------------------------------------------------

def first_int(value, default=1):
    """Best-effort extraction of the first integer in a value (str, int, list)."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        return first_int(value[0], default) if value else default
    m = re.search(r'\d+', str(value))
    return int(m.group()) if m else default


def to_float(value):
    """Parse '750', '1/2', '3 1/2', '1,5' into a float. Returns 0.0 on failure."""
    s = str(value).strip().replace(',', '.')
    try:
        if ' ' in s:  # mixed number, e.g. '3 1/2'
            whole, frac = s.split(None, 1)
            return float(Fraction(whole)) + float(Fraction(frac))
        return float(Fraction(s))
    except (ValueError, ZeroDivisionError):
        return 0.0


# -- amount / unit / food splitting --------------------------------------------

# Words that, when they directly follow an amount, are a measuring/counting unit
# rather than the food item. Kept conservative on purpose: only genuine units
# (measure symbols + counting nouns), NOT foods, so that e.g. '10 olives noires'
# keeps 'olives' as food (old 'first word = unit' heuristic got this wrong).
# A few languages (English + French, the project's targets); extend freely.
_UNIT_WORDS = {
    # measure symbols
    'g', 'kg', 'l', 'cl', 'dl', 'ml',
    # English units of measure
    'cup', 'cups', 'cupful', 'cupfuls',
    'tablespoon', 'tablespoons', 'tbsp',
    'teaspoon', 'teaspoons', 'tsp',
    'spoon', 'spoons', 'scoop', 'scoops',
    'pinch', 'pinches',
    'slice', 'slices', 'piece', 'pieces', 'serving', 'servings',
    'ounce', 'ounces', 'lb', 'lbs', 'pound', 'pounds',
    'can', 'cans', 'bottle', 'bottles', 'jar', 'jars',
    'pack', 'packs', 'package', 'packages', 'box', 'boxes', 'tray', 'trays',
    'bunch', 'bunches', 'stick', 'sticks', 'sheet', 'sheets',
    'roll', 'rolls', 'head', 'heads', 'cloves', 'clove',
    # French units of measure (counting nouns / mesure words)
    'cuillère', 'cuillères', 'cuillerée', 'cuillerées',
    'pincée', 'pincées',
    'tranche', 'tranches',
    'boule', 'boules',
    'gousse', 'gousses',
    'morceau', 'morceaux',
    'feuille', 'feuilles',
    'brin', 'brins',
    'bouquet', 'bouquets',
    'botte', 'bottes',
    'tige', 'tiges',
    'filet', 'filets',
    'galette', 'galettes',
    'rouleau', 'rouleaux',
    'dose', 'doses',
    'part', 'parts',
    'c.à.s', 'cà s', 'c.à.c', 'cà c',
    'cs', 'cc', 'cuil', 'cuils',
    'tasse', 'tasses',
    'verre', 'verres',
    'poignée', 'poignées',
    'sachet', 'sachets',
    'boîte', 'boite', 'boites',
    'bocal', 'bocaux',
    'pot', 'pots',
    'cube', 'cubes',
}

# Multi-word (or dot-abbreviated) units that must be matched as a phrase before
# the single-word walk (e.g. 'cuillères à soupe' = tablespoon; the walk alone
# would stop at 'à'). Each entry is (raw prefix, canonical unit name); the raw
# prefix is matched verbatim (lowercased) and a different spelling canonicalized
# ('c. a soupe' -> 'c. à soupe', 'cc' -> 'c. c.'). Order matters: longer/more
# specific prefixes first.
_COMPOUND_UNITS = (
    ('cuillères à soupe', 'cuillères à soupe'),
    ('cuillères à café', 'cuillères à café'),
    ('cuillerées à soupe', 'cuillerées à soupe'),
    ('cuillerées à café', 'cuillerées à café'),
    ('cuillère à soupe', 'cuillère à soupe'),
    ('cuillère à café', 'cuillère à café'),
    ('cuiller à soupe', 'cuiller à soupe'),
    ('cuiller à café', 'cuiller à café'),
    ('c. à soupe', 'c. à soupe'),
    ('c. a soupe', 'c. à soupe'),
    ('c. à café', 'c. à café'),
    ('c. a cafe', 'c. à café'),
    ('c. à thé', 'c. à thé'),
    ('c. a the', 'c. à thé'),
    ('c. a.c', 'c. c.'),
    ('c.a.c', 'c. c.'),
    ('c. c.', 'c. c.'),
    ('c.c.', 'c. c.'),
    ('c.c', 'c. c.'),
    ('c. c', 'c. c.'),
    ('cc', 'c. c.'),
    ('c. a.s', 'c. à soupe'),
    ('c.a.s', 'c. à soupe'),
    ('c. a.thé', 'c. à thé'),
    ('c.a.thé', 'c. à thé'),
    ('c. a.the', 'c. à thé'),
    ('c.a.the', 'c. à thé'),
)

# Leading connective words to drop from the front of the food part
# ('tranches de chorizo' -> food 'chorizo', not 'de chorizo').
# 'comble' / 'rase' are spoon fill-level descriptors ('1 c. à soupe rase de farine'
# -> food 'farine').
_CONNECTORS = {'de', 'des', 'du', 'au', 'aux', 'a', 'à', 'of', 'and', 'comble', 'rase'}


def _norm_unit(token):
    """Normalize a token for unit-lookup (lowercase, strip trailing punctuation)."""
    return token.lower().strip(' ,.;:()')


def _strip_leading_connectors(tokens):
    """Drop leading connective words (de / d' / of / à …) from a token list."""
    i = 0
    while i < len(tokens) and _norm_unit(tokens[i]) in _CONNECTORS:
        i += 1
    return tokens[i:]


def _trim_leading_apostrophe(food):
    """'d'origan' -> 'origan' (French elision glued onto the first word)."""
    if len(food) > 2 and food[0] == "d" and food[1] in "‘’'" and food[2].isalpha():
        return food[2:]
    return food


def split_ingredient(text):
    """
    Split a raw ingredient string into (amount, unit, food).

    Heuristic (no DB, no external unit dictionary). A word is only treated as
    the *unit* when it is a recognized measuring/counting word; otherwise
    everything after the amount stays as *food*. This keeps French such as
    '1 fromage frais', '1 saumon ou truite fumé' or '1 Pâte feuilletée HERTA
    Trésor de Grand-Mère' intact (no spurious unit), while still splitting
    '1 galette de blé', '3 tranches de chorizo', '20 cl de lait', '140 g de X'.
    A conservative guess (food = everything) is safer than a wrong unit, since
    the preview is user-editable before saving.
    """
    text = text.strip()
    m = _AMOUNT_HEAD_RE.match(text)
    if not m:
        return 0.0, None, text
    amount = to_float(m.group(0).strip())
    rest = text[m.end():].strip()
    if not rest:
        return amount, None, ''

    lower = rest.lower()
    # 1) known multi-word / abbreviated unit phrase at the start (e.g. 'cuillères à soupe')
    for prefix, canonical in _COMPOUND_UNITS:
        if lower.startswith(prefix) and (len(lower) == len(prefix) or lower[len(prefix)] == ' '):
            unit = canonical
            food = _trim_leading_apostrophe(' '.join(_strip_leading_connectors(rest[len(prefix):].split())).strip())
            return amount, unit, food or rest
    # 2) one or more single unit words in a row at the start
    tokens = rest.split()
    j = 0
    while j < min(len(tokens), 3) and _norm_unit(tokens[j]) in _UNIT_WORDS:
        j += 1
    if j:
        unit = ' '.join(tokens[:j])
        food = _trim_leading_apostrophe(' '.join(_strip_leading_connectors(tokens[j:])).strip())
        return amount, unit, food or rest
    # 3) no recognized unit -> everything after the amount is the food
    return amount, None, rest


def iso8601_to_minutes(value):
    """Convert an ISO 8601 duration (PT10M, PT1H30M, ...) to whole minutes."""
    if value is None:
        return 0
    s = str(value).strip()
    m = _DURATION_RE.search(s)
    if not m:
        # e.g. '10 min', 'about 1 hour'
        mm = re.search(r'\d+', s)
        return int(mm.group()) if mm else 0
    d = int(m.group('days') or 0)
    h = int(m.group('hours') or 0)
    mi = int(m.group('minutes') or 0)
    return d * 1440 + h * 60 + mi


# --- JSON-LD discovery ------------------------------------------------------

def extract_jsonld(html):
    """Return a list of decoded JSON-LD objects embedded in `html`."""
    blocks = []
    for raw in _JSONLD_RE.findall(html or ''):
        raw = raw.strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return blocks


def collect_recipe_nodes(node, out):
    """Recursively collect every dict in `node` that is a schema.org Recipe."""
    if isinstance(node, dict):
        t = node.get('@type')
        types = [t] if isinstance(t, str) else (t or [])
        if 'Recipe' in types:
            data = {k: v for k, v in node.items() if k not in ('@context', '@type')}
            out.append(data)
        for v in node.values():
            collect_recipe_nodes(v, out)
    elif isinstance(node, list):
        for item in node:
            collect_recipe_nodes(item, out)


def find_recipes(html):
    """Return the list of schema.org Recipe objects found in `html`."""
    out = []
    for block in extract_jsonld(html):
        collect_recipe_nodes(block, out)
    return out


# --- images --------------------------------------------------------------------

def image_values(value):
    """Normalize a recipe `image` field (str | list | dict) into a list of URLs."""
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(image_values(v))
        return out
    if isinstance(value, dict):
        if 'url' in value:
            v = value['url']
        elif 'value' in value:
            v = value['value']
        else:
            return []
        if not isinstance(v, str):
            return []
        return [unescape(v)] if v.startswith('http') else []
    if isinstance(value, str):
        return [unescape(value)] if value.startswith('http') else []
    return []


def meta_images(html):
    """og:image / twitter:image candidates from the HTML head."""
    out = []
    for prop in ('og:image', 'twitter:image'):
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % re.escape(prop),
            html or '', re.I | re.S,
        )
        if m and m.group(1).startswith('http'):
            out.append(unescape(m.group(1)))
    return out


def dedupe(urls):
    """Drop duplicates (order-preserving), keeping only http(s) values."""
    seen = set()
    out = []
    for u in urls:
        if isinstance(u, str) and u.startswith('http') and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# --- keywords --------------------------------------------------------------------

def keyword_strings(data):
    """Gather flat keyword strings from the various schema.org keyword fields."""
    raw = []
    for key in ('keywords', 'recipeCategory', 'recipeCuisine', 'suitableForDiet'):
        v = data.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            raw.extend([p for p in re.split(r'[,/]', v) if p.strip()])
        elif isinstance(v, list):
            raw.extend([str(x) for x in v if str(x).strip()])
    author = data.get('author')
    if isinstance(author, str) and author.strip():
        raw.append(author.strip())
    elif isinstance(author, list):
        for a in author:
            if isinstance(a, str):
                raw.append(a)
            elif isinstance(a, dict) and a.get('name'):
                raw.append(a['name'])
    return raw


def make_keyword(name, request):
    """Keyword payload, resolving against existing `Keyword`s when a request
    (with a space) is available."""
    name = clean(name)
    if not name:
        return None
    if request is not None:
        try:
            from cookbook.models import Keyword
            k = Keyword.objects.filter(name__iexact=name, space=getattr(request, 'space', None)).first()
            if k:
                return {'id': k.id, 'label': k.name, 'name': k.name, 'import_keyword': True}
        except Exception:
            pass
    return {'id': None, 'label': name, 'name': name, 'import_keyword': True}


def unique_keywords(names, request=None):
    """Ordered, case-insensitive-deduplicated list of keyword payloads."""
    out = []
    seen = set()
    for k in names:
        label = (k or '').strip()
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        kw = make_keyword(label, request)
        if kw:
            out.append(kw)
    return out
