"""
Parser backend: schema.org `Recipe` JSON-LD embedded in the page.

Preferred path — covers the large majority of recipe sites (the same standard
the built-in `recipe-scrapers` import relies on) with zero third-party
dependencies. Shared helpers live in :mod:`import_web.utils`.
"""

import re

from . import utils


def parse(ctx):
    """
    Build an importable recipe from the first schema.org Recipe JSON-LD block
    in ``ctx.html``.

    :return: ``(recipe_dict, note, data)`` on success where ``data`` is the raw
        JSON-LD recipe block (used for image collection), ``None`` if no JSON-LD
        recipe could be found.
    """
    recipes = utils.find_recipes(ctx.html)
    if not recipes:
        return None
    data = recipes[0]
    recipe = build_recipe(data, ctx.url, ctx.request)
    return recipe, f'Parsed from schema.org JSON-LD ({recipe["name"]!r})', data


def build_recipe(data, url, request=None):
    """Convert a schema.org Recipe dict into Tandoor's SourceImportRecipe shape."""
    name = utils.strip_outer_quotes(utils.clean(data.get('name') or '')) or 'Imported Recipe'
    description = utils.clean(data.get('description') or '')[:512]

    servings = utils.first_int(data.get('recipeYield'))
    servings_yaml = data.get('recipeYield')
    servings_text = ''
    if isinstance(servings_yaml, str):
        servings_text = re.sub(r'\d+', '', servings_yaml).strip()[:32]

    working_time = utils.iso8601_to_minutes(data.get('prepTime'))
    waiting_time = utils.iso8601_to_minutes(data.get('cookTime'))
    if working_time + waiting_time == 0:
        working_time = utils.iso8601_to_minutes(data.get('totalTime'))

    image = ''
    for candidate in utils.image_values(data.get('image')):
        if candidate.startswith('http'):
            image = candidate
            break

    keywords = utils.unique_keywords(utils.keyword_strings(data), request)

    def clean_instruction(instr):
        s = utils.clean(instr)
        return s.replace('\n', '  \n')

    steps = []
    instructions = data.get('recipeInstructions')
    if isinstance(instructions, str):
        steps = [{'instruction': clean_instruction(instructions), 'ingredients': [], 'show_ingredients_table': True}]
    elif isinstance(instructions, list):
        for i in instructions:
            text = i if isinstance(i, str) else (i.get('text') if isinstance(i, dict) else str(i))
            text = clean_instruction(text)
            if text:
                steps.append({'instruction': text, 'ingredients': [], 'show_ingredients_table': True})
    if not steps:
        steps = [{'instruction': '', 'ingredients': [], 'show_ingredients_table': True}]

    for raw_ing in (data.get('recipeIngredient') or []):
        raw_ing = utils.clean(raw_ing)
        if not raw_ing:
            continue
        amount, unit, food = utils.split_ingredient(raw_ing)
        steps[0]['ingredients'].append({
            'amount': amount,
            'food': {'name': food or raw_ing},
            'unit': {'name': unit} if unit else None,
            'note': '',
            'original_text': raw_ing,
        })

    return {
        'name': name[:128],
        'description': description,
        'servings': servings,
        'servings_text': servings_text,
        'working_time': working_time,
        'waiting_time': waiting_time,
        'image_url': image or None,
        'keywords': keywords,
        'steps': steps,
        'properties': [],
        'source_url': url or '',
        'internal': True,
    }


def collect_images(data, html, url):
    """Return a deduplicated list of candidate image URLs for the recipe."""
    candidates = []
    for candidate in utils.image_values(data.get('image')):
        if candidate.startswith('http'):
            candidates.append(candidate)
    candidates.extend(utils.meta_images(html))
    return utils.dedupe(candidates)
