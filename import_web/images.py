"""
Server-side recipe-image cache for the `import_web` plugin.

Instead of making the browser load the recipe image straight from the remote
site (hotlinking — breaks on CORS/anti-hotlink sites, and hits the origin a
second time when the recipe is saved), this module:

    1. fetches the remote image on the server — first through
       ``cookbook.helper.HelperFunctions.safe_request`` (``requests-hardened``,
       SSRF-checked) and, only if that is blocked by a WAF, retried with a
       plain browser fingerprint, exactly like :mod:`import_web.fetch` does
       for the recipe page itself. SSRF refusals (private/loopback targets)
       are terminal and never retried, so the protection is never weakened;
    2. stores the bytes under ``settings.MEDIA_ROOT`` — persisted across
       restarts and shared by every gunicorn worker (in-memory would lose the
       cache on restart and is not shared across workers);
    3. serves them back through :class:`import_web.views.CachedImageView` at
       ``import-web/image/<key>/``.

The same bytes are available to the client for the *save* step (it uploads
them back as a multipart file), so the final ``RecipeImage`` endpoint never
has to re-download anything.
"""

import hashlib
import os
import urllib.parse

MAX_IMAGE_BYTES = 30 * 1024 * 1024  # 30 MB: plenty for hi-res recipe photos

ALLOWED_CONTENT_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'image/svg+xml': '.svg',
    'image/bmp': '.bmp',
}

CONTENT_TYPE_BY_EXT = {v: k for k, v in ALLOWED_CONTENT_TYPES.items()}

_EXT_BY_SUFFIX = {
    '.jpg': '.jpg', '.jpeg': '.jpg', '.png': '.png', '.webp': '.webp',
    '.gif': '.gif', '.svg': '.svg', '.bmp': '.bmp',
}


def cache_dir():
    from django.conf import settings
    target = os.path.join(settings.MEDIA_ROOT, 'import-web-cached-images')
    os.makedirs(target, exist_ok=True)
    return target


def key_for(url):
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


def _extension(url, content_type):
    """Pick a file extension from the response content-type, else the URL suffix."""
    ext = ALLOWED_CONTENT_TYPES.get((content_type or '').split(';')[0].strip().lower())
    if not ext:
        suffix = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
        ext = _EXT_BY_SUFFIX.get(suffix, '.jpg')
    return ext


def lookup_local(url_path):
    """Resolve a stored /import-web/image/<name>/ URL to its file on disk.

    Returns the absolute path or ``None``. Only files owned by this plugin
    (under :func:`cache_dir`) are considered, and the name must start with a
    valid 64-char sha256 key, so a crafted URL cannot reach other media files.
    """
    if not url_path:
        return None
    path = urllib.parse.urlsplit(url_path).path
    parts = [p for p in path.split('/') if p]
    if len(parts) < 3 or '/'.join(parts[:2]) != 'import-web/image':
        return None
    name = parts[2]
    base_name = name.split('.')[0]
    if len(base_name) != 64 or not set(base_name) <= set('0123456789abcdef'):
        return None
    candidate = os.path.join(cache_dir(), name)
    if not os.path.isfile(candidate):
        return None
    if not os.path.realpath(candidate).startswith(os.path.realpath(cache_dir()) + os.sep):
        return None
    if not (0 < os.path.getsize(candidate) <= MAX_IMAGE_BYTES):
        return None
    return candidate


def find_by_key(key):
    for entry in os.listdir(cache_dir()):
        if entry.startswith(key):
            return os.path.join(cache_dir(), entry)
    return None


def fetch_to_bytes(url, referer=None):
    """Fetch ``url`` and return ``(bytes, content_type)`` or ``None``.

    Keeps the SSRF protection of ``requests-hardened`` when it is importable
    (a private/loopback target is refused, never retried), and tolerates
    WAF/anti-bot blocks with a plain browser-fingerprinted retry — mirroring
    :func:`import_web.fetch.fetch_page`. ``referer`` (the recipe page URL) is
    forwarded because some CDNs check it before serving an image.
    """
    headers = {
        'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
        'Accept': 'image/avif,image/webp,image/png,image/*,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
        'Sec-Fetch-Dest': 'image',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'cross-site',
    }
    if referer:
        headers['Referer'] = referer

    def download(resp):
        if getattr(resp, 'ok', False) is False:
            return None
        ctype = (getattr(resp, 'headers', {}).get('Content-Type') or '').lower()
        data = b''
        try:
            for chunk in resp.iter_content(chunk_size=65536):
                data += chunk
                if len(data) > MAX_IMAGE_BYTES:
                    return None
        except Exception:
            return None
        if not data:
            return None
        return data, ctype

    safe_request = None
    try:
        from cookbook.helper.HelperFunctions import safe_request as _sr
        safe_request = _sr
    except Exception:
        safe_request = None

    from . import fetch

    if safe_request is not None:
        try:
            result = download(safe_request('GET', url, headers=headers, stream=True))
        except Exception as exc:
            # A refused/failed fetch. If the target is a private/loopback host
            # (SSRF protection), that is terminal — never fall back to a plain
            # client, which would bypass the protection.
            if fetch.is_ssrf_error(exc):
                return None
            result = None
        if result is not None:
            return result
        # WAF/anti-bot block or transient error -> fall through to the retry.

    resp = None
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=(2, 20), stream=True)
    except Exception:
        resp = None
    if resp is not None:
        result = download(resp)
        if result is not None:
            return result
        status = getattr(resp, 'status_code', None)
        if status not in fetch.WAF_BLOCKED:
            # genuine application answer (404/500/...) or a non-image body —
            # a different TLS fingerprint would not change that, so stop here.
            return None
        # WAF/anti-bot block -> escalate to the TLS-impersonating client below.
    # curl_cffi Chrome TLS impersonation (optional dependency) — the strongest
    # tier, used only for WAF-fronted CDNs that fingerprint the handshake.
    cf = fetch._curl_cffi_get(url, headers=headers, timeout=30, stream=True)
    if cf is None:
        return None
    return download(cf)


def store_url(url, referer=None):
    """Cache ``url`` on disk.

    Returns a stored ``/import-web/image/<name>/`` URL (suitable for both the
    preview ``<img>`` tag and the save step), or ``None`` when the image
    could not be fetched or is not a supported image type. Reuses an existing
    cache entry when one is present, so it is cheap to call per request.
    """
    key = key_for(url)
    existing = find_by_key(key)
    if existing:
        return '/import-web/image/{}/'.format(os.path.basename(existing))

    result = fetch_to_bytes(url, referer)
    if result is None:
        return None
    data, content_type = result

    ctype = (content_type or '').split(';')[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        # unknown content type: only accept well-known image suffixes, so the
        # cache never stores HTML error pages or other garbage.
        suffix = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
        if suffix not in _EXT_BY_SUFFIX:
            return None

    name = key + _extension(url, content_type)
    target = os.path.join(cache_dir(), name)
    tmp = target + '.part'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, target)
    return '/import-web/image/{}/'.format(name)
