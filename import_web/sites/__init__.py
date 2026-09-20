"""
Per-site adapters for the `import_web` plugin.

Each site that needs special handling gets one module here (e.g.
`marmiton.py`) with a module-level ``ADAPTER`` that implements
:class:`~import_web.sites.base.SiteAdapter`. Adapters are looked up by the
registrable domain of the source URL (see :func:`find_adapter`); everything
else goes through the generic JSON-LD / recipe-scrapers path.

Add a site by creating a module here — :func:`_scan` picks it up at import
time, so no manual registration list to maintain.
"""

import os
import pkgutil

from .base import SiteAdapter, SiteContext
from ..utils import page_domain


class AdapterRegistry:
    """Maps registrable domains (or subdomain patterns) to SiteAdapter instances."""

    def __init__(self):
        self._exact = {}          # domain -> adapter
        self._patterns = []       # (pattern, adapter) for ``*.example.com`` style

    def register(self, adapter):
        for domain in adapter.domains():
            if domain.startswith('*.'):
                self._patterns.append((domain[2:], adapter))
            else:
                self._exact[domain] = adapter

    def find(self, url):
        domain = page_domain(url)
        if not domain:
            return None
        if domain in self._exact:
            return self._exact[domain]
        for base, adapter in self._patterns:
            if domain == base or domain.endswith('.' + base):
                return adapter
        return None


registry = AdapterRegistry()


def find_adapter(url):
    """Return the SiteAdapter registered for the URL's domain, or ``None``."""
    return registry.find(url)


def _scan():
    here = os.path.dirname(__file__)
    for mod in pkgutil.iter_modules([here]):
        if mod.name.startswith('_'):
            continue
        try:
            module = __import__(f'{__name__}.{mod.name}', fromlist=['ADAPTER'])
        except Exception:
            continue  # a broken adapter must never break generic imports
        adapter = getattr(module, 'ADAPTER', None)
        if isinstance(adapter, SiteAdapter):
            registry.register(adapter)


_scan()


__all__ = ['AdapterRegistry', 'SiteAdapter', 'SiteContext', 'find_adapter', 'registry']
