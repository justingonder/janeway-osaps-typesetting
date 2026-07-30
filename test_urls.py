"""
A URLconf for the plugin's own tests.

In a running install, `core/include_urls.py` mounts a plugin's URLs only if an
enabled `Plugin` row already exists in the database when that module is
imported. Under the test runner the database is created empty, so by the time
anything imports the URLconf there is no row and none of this plugin's view
names are reversible -- `reverse("osaps_typesetting_articles")` raises
NoReverseMatch, and so does every redirect inside the views.

Creating the row and reloading `core.include_urls` would work but mutates
process-global URL state that leaks into the rest of the suite. Instead the
tests point `ROOT_URLCONF` here, which mounts the plugin alongside everything
core provides, and Django restores the real URLconf afterwards.

The prefix is derived the same way `core/include_urls.py` derives it, from
`Plugin.best_name(slug=True)` -- `slugify(DISPLAY_NAME.lower())` -- so that
renaming DISPLAY_NAME cannot leave the tests passing against a path the real
install does not serve.
"""

from django.urls import include, re_path
from django.utils.text import slugify

# core.urls is the real ROOT_URLCONF. Building on core.include_urls instead
# would drop the admin, summernote, hijack and -- under the test runner -- the
# debug toolbar, whose middleware then fails to reverse its own djdt namespace
# while rendering any page.
from core.urls import handler404, handler500  # noqa: F401
from core.urls import urlpatterns as core_urlpatterns
from plugins.osaps_typesetting import plugin_settings

PLUGIN_URL_PREFIX = slugify(plugin_settings.DISPLAY_NAME.lower())

# A new list: core's urlpatterns must not be mutated.
urlpatterns = list(core_urlpatterns) + [
    re_path(
        r"^plugins/{0}/".format(PLUGIN_URL_PREFIX),
        include("plugins.osaps_typesetting.urls"),
    ),
]
