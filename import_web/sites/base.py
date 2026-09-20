"""
Base class for per-site adapters.

A SiteAdapter is a small, self-contained strategy object for a specific recipe
website: it may fetch the page its own way, extract the recipe from markup the
generic JSON-LD / scrapers path cannot handle, or tweak the final result.

An adapter module exposes a module-level ``ADAPTER`` instance; the registry in
:mod:`import_web.sites` discovers them automatically.
"""

from dataclasses import dataclass


@dataclass
class SiteContext:
    """Everything an adapter needs to do its job.

    :param html: the (already fetched) raw HTML of the recipe page
    :param url: canonical URL the page was fetched from
    :param request: optional DRF request (space-scoped keyword resolution,
        IngredientParser); may be None in tests or pure-parse contexts
    """
    html: str
    url: str
    request: object = None


class SiteAdapter:
    """A site-specific recipe extraction strategy.

    Subclasses must implement :meth:`parse`. ``domains()`` returns the
    registrable domains this adapter claims (plain ``'example.com'`` or
    wildcard ``'*.example.com'``); the dispatcher only consults the adapter
    for URLs on those exact domains.

    Default :meth:`parse` returns ``None`` (i.e. "I have nothing better to
    offer"), which lets the dispatcher fall back to the generic path.
    """

    def domains(self):
        raise NotImplementedError

    def parse(self, ctx):
        """Return ``(recipe_dict, note)`` built from :class:`SiteContext`,
        or ``None`` if this adapter could not extract a usable recipe."""
        return None
