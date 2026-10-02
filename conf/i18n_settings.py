"""Languages for the apex: English, French and Spanish.

Tethys imports this through TETHYS_PORTAL_CONFIG.ADDITIONAL_SETTINGS_FILES and copies every name in
__all__ onto the settings module, the same bridge email_settings uses.

LANGUAGES is narrowed from Django's 99 so a browser cannot pick a language with no catalog, and
LANGUAGE_CODE has to be one of them or Django's checks fail at boot. LOCALE_PATHS names the app's
catalog by path because Tethys apps are not in INSTALLED_APPS, so Django never looks inside them.
"""

from importlib.util import find_spec
from pathlib import Path

__all__ = ["LANGUAGES", "LANGUAGE_CODE", "LOCALE_PATHS"]

LANGUAGE_CODE = "en"

LANGUAGES = [
    ("en", "English"),
    ("fr", "Français"),
    ("es", "Español"),
]


def locale_paths():
    """Return the portal's catalog folder, then the viewer app's when it is installed."""
    paths = [str(Path(__file__).resolve().parent / "locale")]
    spec = find_spec("tethysapp.uffis_forecasts")
    if spec and spec.submodule_search_locations:
        paths.append(str(Path(next(iter(spec.submodule_search_locations))) / "locale"))
    return paths


LOCALE_PATHS = locale_paths()
