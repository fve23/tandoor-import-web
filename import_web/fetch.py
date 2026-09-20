"""
HTTP fetching layer for the `import_web` plugin.

Fetches a public web page while tolerating WAF/anti-bot blocks, without ever
weakening the SSRF protection provided by `requests-hardened`:

    1. Prefer Tandoor's SSRF-hardened `safe_request` when importable. If the
       upstream returns a WAF/anti-bot code (401/402/403/429/460/503), retry.
    2. Fall back to plain `requests` with a realistic browser fingerprint,
       which is what a real browser sends and what many WAFs accept.
    3. If that is still blocked, retry with `curl_cffi` impersonating a real
       Chrome TLS/HTTP2 stack (JA3) — some edge WAFs (e.g. Akamai) fingerprint
       the TLS handshake itself. `curl_cffi` is an optional dependency.

SSRF refusals (target resolves to a loopback/private IP) are terminal: they are
returned as the `'forbidden-host'` sentinel and are never retried.
"""

# Upstream status codes that usually mean "your client fingerprint is not
# welcome" (WAF / anti-bot) rather than a real application error. A plain
# browser-like request for the same URL often succeeds where the hardened one
# fails, so these are the only statuses that justify a more permissive retry.
WAF_BLOCKED = {401, 402, 403, 429, 460, 503}

HARDENED_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
}

BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
}

# Sentinel error strings understood by views.RecipeFromUrlView.
ERROR_FORBIDDEN_HOST = 'forbidden-host'
ERROR_NO_CLIENT = 'no-client'
ERROR_NETWORK = 'network-error'


def response_text(resp):
    """Best-effort extraction of the response body as raw text.

    Note: this must NOT run the page through :func:`import_web.utils.clean`
    (tag-stripping) — the parser backends need the raw HTML as the page served
    it, with all its `<script type="application/ld+json">` blocks intact.
    """
    text = getattr(resp, 'text', '') or ''
    if not text:
        text = getattr(resp, 'content', b'').decode('utf-8', errors='replace')
    return text.lstrip('\ufeff')


def _curl_cffi_get(url, headers=None, timeout=30, stream=False):
    """Single attempt with a *full* Chrome TLS/HTTP2 fingerprint via
    ``curl_cffi`` (an optional dependency — see :mod:`import_web.setup_repo`).

    Some edge WAFs (e.g. Akamai, which fronts foodnetwork.com) fingerprint the
    TLS handshake itself (JA3/JA4) rather than the HTTP headers, so a plain
    browser-headers request still gets 403. Impersonating the exact client
    stack of a real browser gets through. Each ``impersonate`` profile ships as
    a separate native library, not every build has all of them, so we probe the
    profile names we care about in order.

    ``stream=True`` keeps the body for chunked reading (large images) instead of
    downloading it eagerly.

    Raises on a real network failure; returns ``None`` only when the optional
    dependency (or every profile) is unavailable.
    """
    try:
        from curl_cffi import requests as _cf
    except Exception:
        return None
    kwargs = {'stream': stream}
    if headers:
        kwargs['headers'] = headers
    # Impersonate profiles that exist in common curl_cffi builds, newest first.
    for impersonate in ('chrome150', 'chrome146', 'chrome145', 'chrome142',
                        'chrome136', 'chrome133a', 'chrome131', 'chrome124',
                        'chrome120', 'chrome119', 'chrome116', 'chrome'):
        try:
            return _cf.get(url, impersonate=impersonate, timeout=timeout, **kwargs)
        except Exception as exc:
            # Skip profiles this build does not ship; surface real errors.
            if 'mpersonat' in str(exc) or 'mpersonat' in type(exc).__name__:
                continue
            raise
    return None


def browser_get(url, user_agent=None, referer=None):
    """Return a response object using the strongest available browser
    fingerprint, or ``None`` when no client succeeded.

    Tier order: plain ``requests`` with a realistic browser header set (what a
    real browser sends and what most WAFs accept), then — only if that came back
    WAF-blocked — ``curl_cffi`` Chrome TLS impersonation (an optional
    dependency). A genuine application answer (404/500/...) is returned
    verbatim without an extra retry, so the origin is never re-hit uselessly.

    A caller that wants a ``text``/``status`` result should pass the response
    through :func:`response_text` / check ``status_code``.
    """
    headers = dict(BROWSER_HEADERS)
    if user_agent:
        headers['User-Agent'] = user_agent
    if referer:
        headers['Referer'] = referer

    resp = None
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=(2, 15))
    except Exception:
        pass  # no client / network error -> try the stronger tier below

    if resp is not None:
        status = getattr(resp, 'status_code', None)
        if getattr(resp, 'ok', False) or status not in WAF_BLOCKED:
            return resp
        # WAF/anti-bot block -> escalate to the TLS-impersonating client.

    # Tier 3 must present a *coherent* real-browser identity. The curl_cffi
    # impersonation profile drives its own User-Agent to match its TLS (JA3)
    # fingerprint; overriding it with a caller-supplied (possibly non-browser)
    # User-Agent re-creates the very UA/TLS mismatch that edge WAFs (Akamai,
    # and friends fronting allrecipes.com) reject with a 460. So only forward
    # the optional referer and let the profile own the identity headers.
    cf_headers = {'Referer': referer} if referer else None
    cf = _curl_cffi_get(url, headers=cf_headers, timeout=30)
    if cf is not None:
        return cf
    # curl_cffi unavailable (not installed) -> hand back whatever we got.
    return resp


def is_ssrf_error(exc):
    """True if the fetch was refused because the host resolved to a private or
    loopback IP (the SSRF protection in `requests-hardened`). We must NOT loosen
    that with a fallback, so such errors are terminal."""
    name = exc.__class__.__name__
    if 'InvalidIPAddress' in name or 'SSRF' in name:
        return True
    return 'Forbidden IP address' in str(exc)


def fetch_page(url, user_agent=None):
    """
    Fetch a public web page, tolerating WAF/anti-bot blocks.

    :return: ``(text, None)`` on success, ``(None, error)`` on failure where
        ``error`` is either an int (a non-block HTTP status code) or one of the
        ``ERROR_*`` sentinel strings.
    """
    hardened_headers = dict(HARDENED_HEADERS)
    hardened_headers['User-Agent'] = user_agent or HARDENED_HEADERS['User-Agent']

    # 1) SSRF-hardened path first (imported lazily so the plugin stays importable
    #    without the full cookbook app, matching the historical behaviour).
    safe_request = None
    try:
        from cookbook.helper.HelperFunctions import safe_request as _sr
        safe_request = _sr
    except Exception:
        safe_request = None

    if safe_request is not None:
        try:
            resp = safe_request('GET', url, headers=hardened_headers)
        except Exception as exc:  # a refused/failed fetch, see below
            if is_ssrf_error(exc):
                return None, ERROR_FORBIDDEN_HOST
            # transient / network error -> fall through to the browser retry
        else:
            if getattr(resp, 'ok', True):
                return response_text(resp), None
            status = getattr(resp, 'status_code', None)
            if status not in WAF_BLOCKED:
                return None, status
            # WAF / anti-bot block -> fall through to the browser retry

    # 2) Browser-fingerprinted path (plain `requests` first, then an optional
    #    `curl_cffi` Chrome TLS impersonation — see :func:`browser_get`).
    #    Reached only when the hardened client was absent, network-refused, or
    #    the target responded with a WAF/anti-bot status in :data:`WAF_BLOCKED`
    #    (401/402/403/429/460/503, the latter including Akamai's bot codes).
    #    It is the very same public URL the hardened client already resolved and
    #    IP-checked, so SSRF protection is not weakened; and we do NOT reach here
    #    for a genuine 404/500 from the origin, because those are real
    #    application answers a retry would not change.
    try:
        resp = browser_get(url, user_agent=user_agent or BROWSER_HEADERS['User-Agent'])
    except Exception:
        return None, ERROR_NETWORK
    if resp is None:
        # requests itself could not be imported / no client could reach the host.
        return None, ERROR_NO_CLIENT
    status = getattr(resp, 'status_code', None)
    if getattr(resp, 'ok', False):
        return response_text(resp), None
    return None, status
