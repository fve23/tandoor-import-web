"""
Parser dispatcher for the `import_web` plugin.

Turns an arbitrary web page (its raw HTML plus the canonical URL it was fetched
from) into a dict matching Tandoor's `SourceImportRecipeSerializer` shape, so it
can be fed straight into the recipe preview editor and saved via
`POST /api/recipe/`.

Resolution order:
    1. A site-specific adapter from :mod:`import_web.sites` (when one is
       registered for the page's domain) — the extension point for sites that
       need bespoke fetch/extract/tweak logic.
    2. schema.org `Recipe` JSON-LD embedded in the page (preferred generic
       path; pure stdlib, :mod:`import_web.jsonld`).
    3. The `recipe-scrapers` library (lazy-imported fallback,
       :mod:`import_web.scrapers`).

This module only coordinates; the real work lives in :mod:`import_web.sites`,
:mod:`import_web.jsonld`, :mod:`import_web.scrapers` and :mod:`import_web.utils`.
"""

from . import jsonld, scrapers, sites, utils
from .sites.base import SiteContext


def _adapter_images(recipe, ctx):
    """Image candidates for an adapter-produced recipe dict."""
    candidates = []
    if recipe.get('image_url') and str(recipe['image_url']).startswith('http'):
        candidates.append(recipe['image_url'])
    candidates.extend(utils.meta_images(ctx.html))
    return utils.dedupe(candidates)


def parse_recipe(html, url, request=None):
    """
    Main entry point.

    :param html: raw HTML of the page
    :param url: canonical URL the page was fetched from
    :param request: optional DRF request (used to resolve keywords against the
        user's space and with Tandoor's IngredientParser; may be None for pure
        parsing / in tests)
    :return: (recipe_dict | None, messages, images) where `messages` is a list of
        human-readable notes (the first says which backend won) and `images` is a
        deduplicated list of candidate image URLs (possibly empty).
    """
    ctx = SiteContext(html=html or '', url=url or '', request=request)

    # 1) Site-specific adapters win when registered for this domain.
    adapter = sites.find_adapter(ctx.url)
    if adapter is not None:
        try:
            result = adapter.parse(ctx)
        except Exception:  # an adapter bug must never break generic imports
            result = None
        if result is not None:
            recipe, note = result
            # an adapter may decline (returning no recipe) after inspecting the
            # page; in that case fall through to the generic path
            if recipe is not None:
                return recipe, [note], _adapter_images(recipe, ctx)

    # 2) Generic: schema.org JSON-LD.
    result = jsonld.parse(ctx)
    if result is not None:
        recipe, note, data = result
        return recipe, [note], jsonld.collect_images(data, ctx.html, ctx.url)

    # 3) Generic: recipe-scrapers fallback (wild mode).
    try:
        scraper = scrapers.scrape(ctx.html, ctx.url)
        recipe = scrapers.to_recipe(scraper, ctx.url, ctx.request)
    except Exception as exc:  # noqa: BLE001 - keeps the endpoint robust
        return None, [f'recipe-scrapers fallback failed: {exc.__class__.__name__}'], []
    if not recipe:
        return None, ['recipe-scrapers found no usable recipe either'], []
    return recipe, [scrapers.NOTE], scrapers.images(scraper)
