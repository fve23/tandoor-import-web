"""
LLM transcription-to-recipe for the video-import endpoint.

Takes a spoken recipe transcript (from :mod:`import_web.stt` or supplied
directly) and produces a recipe in Tandoor's ``SourceImportRecipe`` shape,
validated and normalized against the same contract the other backends
(:mod:`import_web.jsonld`, :mod:`import_web.scrapers`) return.

The language model is any OpenAI-compatible chat endpoint, configured via
environment variables:

* ``IMPORT_WEB_LLM_BASE_URL`` — e.g. ``http://host:11434/v1`` (required)
* ``IMPORT_WEB_LLM_API_KEY``  — optional (Ollama does not need one)
* ``IMPORT_WEB_LLM_MODEL``    — e.g. ``qwen3.8:27b``

The module has no import-time third-party dependency beyond :mod:`requests`,
which the rest of the plugin already relies on (see :mod:`import_web.fetch`,
:mod:`import_web.images`).
"""

import json
import os
import re

import requests

from . import utils

DEFAULT_MODEL = 'qwen2.5:14b'
LLM_TIMEOUT = 120


class RecipeExtractionError(Exception):
    """Raised when a valid recipe could not be produced from a transcript."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


SYSTEM_PROMPT = """You are an expert recipe transcriber. You are given a spoken (often auto-captioned or speech-to-text) transcript of a cooking video. Your job is to reconstruct the recipe it describes and return it as a strict JSON object — no prose, no markdown, no code fences — that matches EXACTLY this schema:

{
  "name": string,                    // short recipe title
  "description": string,             // 1-3 sentence summary, no personal commentary
  "servings": integer,               // yield in count (e.g. 4); 0 if unknown
  "servings_text": string,           // e.g. "4 servings" or ""; "" if unknown
  "working_time": integer,          // active prep + cook time in minutes; 0 if unknown
  "waiting_time": integer,          // passive time (proofing, marinating, resting) in minutes; 0 if unknown
  "image_url": null,                // always null here (no image is available)
  "keywords": [string, ...],        // 1-6 short tags (cuisine, diet, course, technique); lowercase
  "steps": [
    {
      "instruction": string,        // one action, imperative, no "Then"/"Next" filler
      "ingredients": [
        {
          "amount": number | null,  // quantity as a decimal if given; null if not stated
          "food": { "name": string },
          "unit": { "name": string } | null,  // the measure (g, cups, tbsp, slice...); null if none stated
          "note": string,           // optional clarification; "" if none
          "original_text": string   // the ingredient phrase as spoken in the transcript
        }
      ],
      "show_ingredients_table": true
    }
  ],
  "properties": [],
  "internal": true
}

Rules:
- Put every mentioned ingredient in the FIRST step's "ingredients" list, once each, grouped logically. Do not repeat an ingredient across steps.
- Amounts are plain decimals (use 0.5 for half). Units stay as spoken ("tbsp", "cups", "g"). If no amount is given, set "amount": null.
- Do NOT invent ingredients, quantities, or steps that are not present in the transcript. Where the transcript is ambiguous or truncated, use your best judgment but stay faithful; do not fabricate details.
- "servings" and "working_time" are integers; use 0 when the value is not inferable.
- Return ONLY the JSON object. No trailing text, no commentary."""


def extract_recipe(transcript, source_url='', request=None):
    """
    Turn a transcript into a normalized, contract-valid recipe dict.

    :param transcript: the spoken recipe text (str).
    :param source_url: the original video/page URL, stored on ``recipe['source_url']``.
    :param request: an optional Django/DRF request; used to resolve existing
        ``Keyword`` rows by name (see :func:`import_web.utils.unique_keywords`).
    :return: a recipe dict in Tandoor's ``SourceImportRecipe`` shape.
    :raises RecipeExtractionError: if the LLM is unconfigured, the call fails,
        or no valid JSON recipe can be recovered from the response.
    """
    if not transcript or not str(transcript).strip():
        raise RecipeExtractionError('No transcript was provided to convert into a recipe.')

    base_url, model, api_key = _cfg()
    raw = _chat(SYSTEM_PROMPT, f'Transcript:\n"""\n{str(transcript).strip()}\n"""', model, base_url, api_key)
    data = _extract_json(raw)

    if isinstance(data, dict) and isinstance(data.get('recipe'), dict):
        data = data['recipe']
    if not isinstance(data, dict):
        raise RecipeExtractionError('The model response did not contain a usable recipe object.')

    return _normalize(data, source_url, request)


def _cfg():
    base_url = (os.environ.get('IMPORT_WEB_LLM_BASE_URL') or '').strip().rstrip('/')
    if not base_url:
        raise RecipeExtractionError(
            'No LLM endpoint is configured. Set IMPORT_WEB_LLM_BASE_URL '
            '(an OpenAI-compatible base URL) to enable recipe extraction.'
        )
    model = (os.environ.get('IMPORT_WEB_LLM_MODEL') or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    api_key = (os.environ.get('IMPORT_WEB_LLM_API_KEY') or '').strip()
    return base_url, model, api_key


def _chat(system, user, model, base_url, api_key):
    url = f'{base_url}/chat/completions'
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'model': model,
        'temperature': 0,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=LLM_TIMEOUT)
    except requests.RequestException as exc:
        raise RecipeExtractionError(f'Could not reach the LLM at {base_url!r}: {exc}') from exc

    if resp.status_code != 200:
        raise RecipeExtractionError(
            f'The LLM endpoint returned HTTP {resp.status_code}: {resp.text[:300]}'
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise RecipeExtractionError('The LLM response was not valid JSON.') from exc

    try:
        return body['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise RecipeExtractionError('The LLM response did not contain a usable message.') from exc


def _extract_json(raw):
    """Parse the model output, tolerating code fences and surrounding prose."""
    if not isinstance(raw, str):
        if isinstance(raw, (dict, list)):
            return raw
        raise RecipeExtractionError('The model returned no content.')

    text = raw.strip()

    fence = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)

    if not text.startswith('{'):
        start = text.find('{')
        if start == -1:
            raise RecipeExtractionError('No JSON object was found in the model response.')
        text = text[start:]
        end = _matching_brace(text)
        if end is not None:
            text = text[:end + 1]

    try:
        return json.loads(text)
    except ValueError as exc:
        raise RecipeExtractionError(f'The model response was not valid JSON: {exc}') from exc


def _matching_brace(text):
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i
    return None


def _normalize(data, source_url, request):
    name = utils.strip_outer_quotes(utils.clean(data.get('name') or '')) or 'Imported Recipe'
    description = utils.clean(data.get('description') or '')[:512]

    servings = _norm_serving(data.get('servings'))
    servings_text = utils.clean(data.get('servings_text') or '')[:32]

    working_time = _norm_minutes(data.get('working_time'))
    waiting_time = _norm_minutes(data.get('waiting_time'))

    image_url = data.get('image_url')
    if image_url is not None and not isinstance(image_url, str):
        image_url = None

    steps_raw = data.get('steps')
    if isinstance(steps_raw, list):
        steps = [_norm_step(s, i) for i, s in enumerate(steps_raw)]
    else:
        steps = []
    if not steps:
        steps = [{'instruction': '', 'ingredients': [], 'show_ingredients_table': True}]

    # Consolidate all ingredients onto the first step (the canonical Tandoor shape).
    all_ingredients = []
    for step in steps:
        all_ingredients.extend(step.pop('ingredients', []))
    seen = set()
    deduped = []
    for ing in all_ingredients:
        unit_name = (ing['unit'] or {}).get('name') or '' if ing['unit'] else ''
        key = (ing['food']['name'].casefold(), unit_name, round(ing['amount'] or 0, 3))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ing)
    for step in steps:
        step['ingredients'] = []
    steps[0]['ingredients'] = deduped

    keywords = _norm_keywords(data.get('keywords'), request)

    return {
        'name': name[:128],
        'description': description,
        'servings': servings,
        'servings_text': servings_text,
        'working_time': working_time,
        'waiting_time': waiting_time,
        'image_url': image_url or None,
        'keywords': keywords,
        'steps': steps,
        'properties': [],
        'source_url': source_url or '',
        'internal': True,
    }


def _norm_serving(value):
    if value is None or isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        v = int(value)
        return v if v >= 1 else 1
    try:
        return utils.first_int(value, default=1)
    except (ValueError, TypeError):
        return 1


def _norm_minutes(value):
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        v = int(value)
        return v if v >= 0 else 0
    try:
        v = int(str(value).strip())
    except (ValueError, TypeError):
        return 0
    return v if v >= 0 else 0


def _norm_step(raw, index):
    if isinstance(raw, str):
        instruction = utils.clean(raw).replace('\n', '  \n')
        return {'instruction': instruction, 'ingredients': [], 'show_ingredients_table': True}

    if not isinstance(raw, dict):
        instruction = utils.clean(str(raw)).replace('\n', '  \n')
        return {'instruction': instruction, 'ingredients': [], 'show_ingredients_table': True}

    instruction = utils.clean(raw.get('instruction') or raw.get('text') or '')
    instruction = instruction.replace('\n', '  \n')

    ingredients_raw = raw.get('ingredients') or raw.get('items') or []
    ingredients = []
    if isinstance(ingredients_raw, list):
        for ing in ingredients_raw:
            normalized = _norm_ingredient(ing)
            if normalized:
                ingredients.append(normalized)

    show_table = raw.get('show_ingredients_table', True)
    if not isinstance(show_table, bool):
        show_table = True

    return {
        'instruction': instruction,
        'ingredients': ingredients,
        'show_ingredients_table': show_table,
    }


def _norm_ingredient(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        text = utils.clean(raw)
        if not text:
            return None
        return _norm_string_ingredient(text)
    if not isinstance(raw, dict):
        return None
    return _norm_dict_ingredient(raw)


def _norm_dict_ingredient(raw):
    food = raw.get('food')
    if isinstance(food, dict):
        food_name = utils.clean(food.get('name') or '')
    elif isinstance(food, str):
        food_name = utils.clean(food)
    else:
        food_name = ''
    if not food_name:
        food_name = utils.clean(raw.get('name') or raw.get('original_text') or '')
    if not food_name:
        return None

    unit = raw.get('unit')
    if isinstance(unit, dict):
        unit_name = utils.clean(unit.get('name') or '')
    elif isinstance(unit, str):
        unit_name = utils.clean(unit)
    elif unit in (None, '', 'None', 'null'):
        unit_name = ''
    else:
        unit_name = utils.clean(str(unit))

    amount = _norm_amount(raw.get('amount'))
    note = utils.clean(raw.get('note') or '')
    original_text = utils.clean(raw.get('original_text') or raw.get('name') or '')
    if not original_text:
        pieces = []
        if amount is not None:
            pieces.append(str(amount))
        if unit_name:
            pieces.append(unit_name)
        pieces.append(food_name)
        original_text = ' '.join(p for p in pieces if p).strip()

    return {
        'amount': amount,
        'food': {'name': food_name},
        'unit': {'name': unit_name} if unit_name else None,
        'note': note,
        'original_text': original_text,
    }


def _norm_string_ingredient(text):
    amount, unit, food = utils.split_ingredient(text)
    if amount == 0.0:
        amount = None
    return {
        'amount': amount,
        'food': {'name': food or text},
        'unit': {'name': unit} if unit else None,
        'note': '',
        'original_text': text,
    }


def _norm_amount(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v > 0 else None
    try:
        s = str(value).strip()
    except (ValueError, TypeError, AttributeError):
        return None
    if not s:
        return None
    f = utils.to_float(s)
    return f if f > 0 else None


def _norm_keywords(raw, request):
    if raw is None:
        return []
    if isinstance(raw, list):
        names = []
        for item in raw:
            n = utils.clean(item) if isinstance(item, str) else ''
            if n:
                names.append(n)
        return utils.unique_keywords(names, request)
    if isinstance(raw, str):
        n = utils.clean(raw)
        if n:
            return utils.unique_keywords([n], request)
    return []
