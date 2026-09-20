"""HTTP views for the `import_web` plugin."""

import os

from django.http import FileResponse, Http404
from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
)
from rest_framework.views import APIView

from . import fetch
from . import images as image_cache
from .parser import parse_recipe

_ERROR_MESSAGES = {
    fetch.ERROR_FORBIDDEN_HOST: _('That address points at a local or private network, so it will not be fetched.'),
    fetch.ERROR_NO_CLIENT: _('The server has no HTTP client available to fetch that page.'),
    fetch.ERROR_NETWORK: _('The server could not load that page (network error).'),
}


def _response_payload(recipe, images, msg='', error=False, status=None, duplicates=None):
    """Build a response matching the built-in `RecipeFromSourceResponseSerializer`
    shape so the existing recipe preview editor can consume it unchanged."""
    return Response({
        'recipe': recipe,
        'recipe_id': None,
        'images': images,
        'error': error,
        'msg': msg,
        'duplicates': duplicates or [],
    }, status=status)


class RecipeFromUrlView(APIView):
    """
    Import a recipe from (almost) any web page.

    Accepts a URL, fetches the page (:mod:`import_web.fetch`), and extracts a
    recipe (:mod:`import_web.parser`): a site-specific adapter when registered,
    else schema.org JSON-LD, else `recipe-scrapers`.

    On success the recipe's first image (if any) is also fetched server-side
    and stored in a local disk cache (:mod:`import_web.images`); the response
    then carries a **local** URL (``/import-web/image/<key>/``) in both
    ``recipe.imageUrl`` and ``images[0]``, so the browser never has to load
    the image from the remote site. The original remote URL is also retained
    in ``images`` as a fallback for clients that cannot reach the local cache
    (e.g. anonymous previews).

    Request body: `{"url": "https://example.com/recipe/some-recipe"}`
    (a raw HTML string may also be passed as `data`, e.g. for a bookmarklet).
    """

    def post(self, request, *args, **kwargs):
        url = (request.data.get('url') or '').strip()
        data = request.data.get('data') or ''

        if not url and not data:
            return _response_payload(None, [], msg=_('Nothing to do.'), error=True,
                                     status=HTTP_400_BAD_REQUEST)

        html = data
        if not html and url:
            html, err = fetch.fetch_page(url, request.META.get('HTTP_USER_AGENT'))
            if html is None:
                if isinstance(err, str):
                    msg = _ERROR_MESSAGES.get(err) or _('The requested page could not be loaded.')
                else:
                    msg = _('The requested page could not be loaded. The server returned %(code)s.') % {'code': err}
                return _response_payload(None, [], msg=msg, error=True,
                                         status=HTTP_400_BAD_REQUEST)

        html = (html or '').lstrip('\ufeff')

        recipe, notes, image_urls = parse_recipe(html, url, request=request)

        if recipe is None:
            msg = notes[-1] if notes else _('No usable recipe data could be found.')
            return _response_payload(None, image_urls, msg=msg, error=True,
                                     status=HTTP_400_BAD_REQUEST)

        # Fetch the recipe's primary image server-side, cache it on disk, and
        # expose it through our own /import-web/image/ route instead of
        # hotlinking the remote site. Failures are non-fatal: the original
        # remote URL is kept in `images` as a fallback, and `imageUrl` stays
        # unset so the preview falls back to images[0] (the remote one).
        local_image = None
        candidate = (recipe.get('image_url') or '')
        if not candidate and image_urls:
            candidate = image_urls[0]
        if candidate.startswith('http'):
            local_image = image_cache.store_url(candidate, referer=url or None)

        final_images = list(image_urls)
        if local_image:
            final_images = [local_image] + [u for u in image_urls if u != local_image]

        if local_image:
            recipe['image_url'] = local_image

        # If we were given the raw page (bookmarklet `data`) rather than a URL,
        # we cannot do duplicate checking against a stable source.
        duplicates = []
        if url:
            try:
                from cookbook.models import Recipe
                space = getattr(request, 'space', None)
                duplicates = list(
                    Recipe.objects.filter(space=space, source_url=url)
                    .values('id', 'name')
                )
            except Exception:
                duplicates = []

        return _response_payload(recipe, final_images, duplicates=duplicates,
                                 status=HTTP_200_OK)


class RecipeFromVideoView(APIView):
    """
    Import a recipe from a cooking video.

    Two input modes (mutually exclusive):

    1. `{"url": "https://youtube.com/watch?v=..."}` — the server fetches
       captions via yt-dlp (:mod:`import_web.stt`), then converts the
       transcript to a recipe with the configured LLM
       (:mod:`import_web.transcript_llm`).

    2. `{"transcript": "..."}` — a plain-text transcript is passed directly
       to the LLM; captions are bypassed entirely (also the fallback when
       the LLM server is unavailable or the URL has no captions).

    Request body: `{"url": "..."} or `{"transcript": "..."}`.
    """

    def post(self, request, *args, **kwargs):
        url = (request.data.get('url') or '').strip()
        transcript = request.data.get('transcript') or ''

        if not url and not transcript.strip():
            return _response_payload(None, [], msg=_('Nothing to do.'), error=True,
                                     status=HTTP_400_BAD_REQUEST)

        images = []
        if url and not transcript.strip():
            from . import stt
            try:
                result = stt.get_transcript(url)
            except stt.TranscriptError as e:
                return _response_payload(None, [], msg=str(e), error=True,
                                         status=HTTP_400_BAD_REQUEST)
            transcript = result.get('text', '')
            image_url = result.get('image_url') or ''
            if image_url:
                images = [image_url]

        from . import transcript_llm
        try:
            recipe = transcript_llm.extract_recipe(transcript, source_url=url, request=request)
        except transcript_llm.RecipeExtractionError as e:
            return _response_payload(None, images, msg=str(e), error=True,
                                     status=HTTP_400_BAD_REQUEST)

        return _response_payload(recipe, images, status=HTTP_200_OK)


class VideoTranscribeView(APIView):
    """
    Stage 1 of the two-step video import: obtain a transcript for the video.

    Splitting this out of :class:`RecipeFromVideoView` lets the front-end show
    a "reading subtitles" status *while* the (slow) caption/Whisper stage runs,
    then kick off the (slow) LLM stage as a second request with its own status.

    Request body: `{"url": "https://youtube.com/watch?v=..."}`.
    On success returns `{"error": false, "text", "title", "image_url", "method"}`.
    """

    def post(self, request, *args, **kwargs):
        url = (request.data.get('url') or '').strip()

        def fail(msg):
            return Response({
                'error': True, 'msg': msg,
                'text': '', 'title': '', 'image_url': '', 'method': '',
            }, status=HTTP_400_BAD_REQUEST)

        if not url:
            return fail(_('Nothing to do.'))

        from . import stt
        try:
            result = stt.get_transcript(url)
        except stt.TranscriptError as e:
            return fail(str(e))

        return Response({
            'error': False, 'msg': '',
            'text': result.get('text', ''),
            'title': result.get('title') or '',
            'image_url': result.get('image_url') or '',
            'method': result.get('method') or '',
        }, status=HTTP_200_OK)


class VideoExtractView(APIView):
    """
    Stage 2 of the two-step video import: turn a transcript into a recipe with
    the configured LLM (:mod:`import_web.transcript_llm`).

    Request body: `{"transcript": "...", "url": "optional source url"}`.
    Returns the standard `RecipeFromSourceResponseSerializer` shape so the
    front-end preview editor consumes it unchanged (images are empty here — the
    video thumbnail comes from stage 1).
    """

    def post(self, request, *args, **kwargs):
        transcript = request.data.get('transcript') or ''
        url = (request.data.get('url') or '').strip()

        if not transcript.strip():
            return _response_payload(None, [], msg=_('Nothing to do.'), error=True,
                                     status=HTTP_400_BAD_REQUEST)

        from . import transcript_llm
        try:
            recipe = transcript_llm.extract_recipe(transcript, source_url=url, request=request)
        except transcript_llm.RecipeExtractionError as e:
            return _response_payload(None, [], msg=str(e), error=True,
                                     status=HTTP_400_BAD_REQUEST)

        return _response_payload(recipe, [], status=HTTP_200_OK)


class CachedImageView(APIView):
    """Serve a previously-fetched recipe image from the local disk cache.

    The URL is produced by :mod:`import_web.images` (``store_url``) and only
    ever resolves to files under ``<MEDIA_ROOT>/import-web-cached-images/``
    that were fetched by this plugin, so no arbitrary path is reachable.
    Authentication is the DRF default (session, required).
    """

    def get(self, request, name=None, *args, **kwargs):
        path = image_cache.lookup_local('/import-web/image/{}/'.format(name))
        if not path:
            raise Http404
        ctype = image_cache.CONTENT_TYPE_BY_EXT.get(
            os.path.splitext(path)[1].lower(), 'application/octet-stream')
        # FileResponse takes ownership of the handle and closes it once
        # streamed; a `with` block would close it before the worker sends it.
        fh = open(path, 'rb')
        try:
            return FileResponse(fh, filename=os.path.basename(path), content_type=ctype)
        except Exception:
            fh.close()
            raise
