"""Per tenant template context.

One portal serves every tenant, so anything that varies by tenant and is not a site setting has to
arrive through here. Tethys appends this to its own processors through settings.CONTEXT_PROCESSORS.

Language is the case that matters. Each tenant's copy is written in that agency's language, but the
html lang attribute is baked as "en" in the Tethys base template, so assistive technology reads the
French and Spanish pages with English pronunciation. There is no site setting for language and
LANGUAGE_CODE is portal wide, which leaves the schema as the only thing that knows.
"""

from django.db import connection

DEFAULT_LANGUAGE = "en"

# Schema name to BCP 47 tag. A tenant absent from here is served in the default language.
TENANT_LANGUAGES = {
    "anacm": "fr",
    "uhm": "fr",
    "insivumeh": "es",
}


def tenant_language(request):
    """Return the language tag for the tenant bound to this connection."""
    schema = getattr(connection, "schema_name", None)
    return {"tenant_language": TENANT_LANGUAGES.get(schema, DEFAULT_LANGUAGE)}
