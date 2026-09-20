"""
Site adapter for Food Wishes (foodwishes.blogspot.com).

Two recurring page shapes need bespoke handling that the generic JSON-LD /
recipe-scrapers path cannot extract:

1. *Inline video recipes.* The recipe body is pasted from Word as a run of
   ``<div class="MsoNormal">`` blocks: an "Ingredients for N ...:" header
   followed by one ingredient per div. There are usually no written
   directions (the steps live in an embedded YouTube video), so we emit a
   single step carrying all the ingredients.

2. *Link-out posts.* The post merely links to the real recipe on another
   site (typically allrecipes.com). We follow the first such link and run
   the normal parser on the fetched page.

Because the registrable domain of a ``*.blogspot.com`` URL is just
``blogspot.com`` (see :func:`import_web.utils.page_domain`), this adapter
claims ``*.blogspot.com`` in :meth:`domains` and self-filters on the exact
foodwishes host inside :meth:`parse`, declining for every other blog on
Google's domain.
"""

import re
from urllib.parse import urlparse

from .base import SiteAdapter


# Exact host we actually want (with optional www). Anything else on
# *.blogspot.com is declined so we never shadow a different blogger's site.
_HOST_RE = re.compile(r'^(?:www\.)?foodwishes\.blogspot\.com$')

# The "Ingredients for ..." line that precedes the ingredient run.
_INGREDIENTS_HEADER_RE = re.compile(r'^\s*ingredients(?:\s+for)?.*?$', re.IGNORECASE)

# A post title like "Food Wishes Video Recipes: <name>" lives in this heading.
_POST_TITLE_RE = re.compile(r"<h3 class=['\"]post-title entry-title['\"][^>]*>(.*?)</h3>", re.S | re.I)
_TITLE_TAG_RE = re.compile(r'<title>(.*?)</title>', re.S | re.I)
_FOODWISHES_TITLE_PREFIX_RE = re.compile(r'^\s*food\s?wishes[^:]*:\s*', re.IGNORECASE)

# Outbound recipe links we may follow (allrecipes first — the common target).
_ALLRECIPES_RE = re.compile(r'href=["\'](https?://(?:www\.)?allrecipes\.com/[^"\'?#]+)["\']', re.I)


def _strip_tags(fragment):
    """Collapse a raw HTML fragment to cleaned plain text (single line)."""
    from .. import utils  # lazy: keeps module import cycle-free

    text = re.sub(r'<br\s*/?>', '  \n', fragment, flags=re.I)
    text = re.sub(r'</div>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = utils.clean(text)
    return re.sub(r'\s+', ' ', text).strip()


def _msonormal_divs(html):
    """Return the clean text of every ``<div class="MsoNormal">...`` block."""
    from .. import utils

    raw = re.findall(r'<div class=["\']MsoNormal["\'][^>]*>(.*?)</div>', html, re.S)
    texts = []
    for block in raw:
        t = re.sub(r'<br\s*/?>', '\n', block, flags=re.I)
        t = re.sub(r'<[^>]+>', ' ', t)
        t = re.sub(r'\s+', ' ', utils.clean(t)).strip()
        if t:
            texts.append(t)
    return texts


def _is_ingredient_line(text):
    """Heuristically decide whether a pasted line is a real ingredient."""
    low = text.lower()
    if text.startswith('('):          # parenthetical notes ("(Note: ...")
        return False
    if text.startswith('*'):          # author tips ("*Remember to drain ...")
        return False
    if low.startswith('based on'):    # attribution lines
        return False
    if 'remember to' in low:
        return False
    return True


def _post_name(html):
    m = _POST_TITLE_RE.search(html)
    if m:
        return _strip_tags(m.group(1))
    m = _TITLE_TAG_RE.search(html)
    if m:
        name = _strip_tags(m.group(1))
        return _FOODWISHES_TITLE_PREFIX_RE.sub('', name).strip()
    return ''


def _extract_ingredients(divs):
    """Given the MsoNormal texts, find the ingredient run after the header.

    Returns ``(list_of_ingredient_strings, servings_int_or_None)``.
    """
    from .. import utils

    header_idx = None
    for i, text in enumerate(divs):
        if _INGREDIENTS_HEADER_RE.match(text) and 'ingredient' in text.lower():
            header_idx = i
            break
    if header_idx is None:
        return [], None

    servings = utils.first_int(divs[header_idx], default=0) or None

    ingredients = []
    for text in divs[header_idx + 1:]:
        if _is_ingredient_line(text):
            ingredients.append(text)
    return ingredients, servings


class FoodWishesAdapter(SiteAdapter):
    def domains(self):
        # The registrable domain is 'blogspot.com'; wildcard claim, then
        # self-filter on the exact host inside parse().
        return ['*.blogspot.com']

    def parse(self, ctx):
        from .. import utils

        host = (urlparse(ctx.url).hostname or '').lower()
        if not _HOST_RE.match(host):
            # Some other *.blogspot.com blog → not our site.
            return None

        divs = _msonormal_divs(ctx.html)
        ingredients, servings = _extract_ingredients(divs)

        # 1) Inline pasted recipe (video-only, ingredients are the payload).
        if ingredients:
            steps = [{'instruction': '', 'ingredients': [], 'show_ingredients_table': True}]
            for raw in ingredients:
                amount, unit, food = utils.split_ingredient(raw)
                steps[0]['ingredients'].append({
                    'amount': amount,
                    'food': {'name': food or raw},
                    'unit': {'name': unit} if unit else None,
                    'note': '',
                    'original_text': raw,
                })
            recipe = {
                'name': (_post_name(ctx.html) or 'Food Wishes Recipe')[:128],
                'description': 'Video recipe imported from Food Wishes.',
                'servings': servings or 1,
                'servings_text': '',
                'working_time': 0,
                'waiting_time': 0,
                'image_url': None,  # _adapter_images() fills this from og:image
                'keywords': utils.unique_keywords(utils.keyword_strings({'keywords': 'food wishes'}), ctx.request),
                'steps': steps,
                'properties': [],
                'source_url': ctx.url or '',
                'internal': True,
            }
            return recipe, 'Parsed inline Food Wishes recipe (video recipe)'

        # 2) Link-out post → follow the first allrecipes link, then re-parse.
        link = _ALLRECIPES_RE.search(ctx.html)
        if link:
            target = link.group(1)
            # Lazy imports: fetch_page/parse_recipe live in modules that
            # (transitively) import this very adapter via the sites registry,
            # so they must not be imported at module-load time.
            from ..fetch import fetch_page
            from ..parser import parse_recipe

            text, error = fetch_page(target, user_agent=_user_agent(ctx.request))
            if text is not None:
                recipe, _notes, _images = parse_recipe(text, target, ctx.request)
                if recipe:
                    recipe['source_url'] = ctx.url or target
                    recipe['name'] = (recipe.get('name') or 'Imported Recipe')[:128]
                    return recipe, f'Followed Food Wishes link to {(urlparse(target).hostname or target)}'
        return None


def _user_agent(request=None):
    """Forward the request User-Agent if present (helps tier-1/2 fetches)."""
    try:
        if request is not None and getattr(request, 'META', None):
            return request.META.get('HTTP_USER_AGENT')
    except Exception:
        pass
    return None


ADAPTER = FoodWishesAdapter()
