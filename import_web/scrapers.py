"""
Parser backend: the `recipe-scrapers` library.

Fallback for pages with no usable schema.org JSON-LD. ``recipe_scrapers`` is
lazy-imported so its heavy dependency tree is only loaded (at all) when the
JSON-LD path has nothing to offer.

When a DRF request is available, ingredients are re-parsed per-ingredient with
Tandoor's own ``cookbook.helper.ingredient_parser.IngredientParser``
(space-aware amount/unit/food/note), falling back to the generic
:func:`import_web.utils.split_ingredient` heuristic.
"""

from . import utils


NOTE = 'Parsed via recipe-scrapers (no usable JSON-LD found)'


def scrape(html, url):
    """Lazy-imported wrapper around ``recipe_scrapers.scrape_html``
    (wild mode, so unsupportted pages are still attempted).

    Raises the library's own exceptions (e.g. ``NoSchemaFoundInWildMode``)
    — the dispatcher in :mod:`import_web.parser` catches them.
    """
    from recipe_scrapers import scrape_html  # lazy on purpose

    return scrape_html(html=html, org_url=url or 'https://urlnotfound.none', supported_only=False)


def to_recipe(scraper, url, request=None):
    """Best-effort mapping of a recipe-scrapers object to our output shape."""
    def safe(fn, default=None):
        try:
            value = fn() if callable(fn) else fn
            return value if value not in (None, '') else default
        except Exception:
            return default

    instructions = []
    try:
        for i in scraper.instructions_list():
            if i and str(i).strip():
                instructions.append(utils.clean(i))
    except Exception:
        pass
    if not instructions:
        inst = safe(scraper.instructions, '')
        if inst:
            instructions = [utils.clean(inst)]
    if not instructions:
        instructions = ['']

    ingredients = _ingredients(scraper, request)

    recipe = {
        'name': (safe(scraper.title, '') or 'Imported Recipe')[:128],
        'description': utils.clean(safe(scraper.description, ''))[:512],
        'servings': utils.first_int(safe(lambda: scraper.yield_(), 1)),
        'servings_text': '',
        'working_time': 0,
        'waiting_time': 0,
        'image_url': safe(scraper.image, ''),
        'keywords': [],
        'steps': [{'instruction': instructions[0], 'ingredients': ingredients, 'show_ingredients_table': True}]
          + [{'instruction': i, 'ingredients': [], 'show_ingredients_table': True} for i in instructions[1:]],
        'properties': [],
        'source_url': url or '',
        'internal': True,
    }
    for key, field in (('prep_time', 'working_time'), ('cook_time', 'waiting_time'), ('total_time', None)):
        value = safe(getattr(scraper, key, None), 0)
        if value:
            recipe[field or 'working_time'] = int(value)
    return recipe


def images(scraper):
    """Best-effort image URL from a scrape_html result (or [] on failure)."""
    try:
        img = scraper.image()
        if isinstance(img, str) and img.startswith('http'):
            return [img]
    except Exception:
        pass
    return []


# --- private --------------------------------------------------------------------

def _ingredient_dict(raw, request=None):
    """Parse one raw ingredient string into Tandoor's ingredient payload."""
    parser = None
    if request is not None:
        try:
            from cookbook.helper.ingredient_parser import IngredientParser
            parser = IngredientParser(request)
        except Exception:
            parser = None
    parsed = None
    if parser is not None:
        try:
            parsed = parser.parse(raw)
        except Exception:
            parsed = None
    if parsed:
        amount, unit, food, note = parsed
        return {
            'amount': amount or 0.0,
            'food': {'name': food or raw},
            'unit': {'name': unit} if unit else None,
            'note': note or '',
            'original_text': raw,
        }
    amount, unit, food = utils.split_ingredient(raw)
    return {
        'amount': amount,
        'food': {'name': food or raw},
        'unit': {'name': unit} if unit else None,
        'note': '',
        'original_text': raw,
    }


def _ingredients(scraper, request=None):
    out = []
    try:
        for x in scraper.ingredients():
            if not x or not str(x).strip():
                continue
            out.append(_ingredient_dict(x, request))
    except Exception:
        pass
    return out
