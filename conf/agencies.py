"""The participating agencies, written down once for the apex.

The public home directory, the apex portal menu and the viewer's panel line all read this list.
It is not read from the tenant table, which holds neither an agency's own name in its own language
nor its seal. Adding or removing a tenant means editing this list.
"""

from django.db import connection
from public_gate import PUBLIC_SCHEMA

# Ordered by country name
AGENCIES = [
    {
        "schema": "abms",
        "short": "ABMS",
        "place": "Antigua and Barbuda",
        "name": "Antigua and Barbuda Meteorological Services",
        "seal": "tenants/abms/abms_logo.png",
        "country": "antigua",
    },
    # Paused at Barbados request
    # {
    #     "schema": "bms",
    #     "short": "BMS",
    #     "place": "Barbados",
    #     "name": "Barbados Meteorological Services",
    #     "seal": "tenants/bms/bms_logo.png",
    #     "country": "barbados",
    # },
    {
        "schema": "anacm",
        "short": "ANACM",
        "place": "Comoros",
        "name": "Agence Nationale de l'Aviation Civile et de la Météorologie",
        "seal": "tenants/anacm/anacm_logo.png",
        "country": "comoros",
    },
    {
        "schema": "insivumeh",
        "short": "INSIVUMEH",
        "place": "Guatemala",
        "name": "Instituto Nacional de Sismología, Vulcanología, Meteorología e Hidrología",
        "seal": "tenants/insivumeh/insivumeh_seal.png",
        "country": "guatemala",
    },
    {
        "schema": "uhm",
        "short": "UHM",
        "place": "Haiti",
        "name": "Unité Hydrométéorologique d'Haïti",
        "seal": None,
        "country": "haiti",
    },
]


def host(agency):
    """Return the agency portal's hostname."""
    return f"{agency['schema']}.uffis.org"


def with_hosts():
    """Return the agencies, each with its portal hostname added."""
    return [{**agency, "host": host(agency)} for agency in AGENCIES]


def public_agencies(request):
    """Add the agency list to templates on the public schema only."""
    if getattr(connection, "schema_name", None) != PUBLIC_SCHEMA:
        return {}
    return {"agencies": with_hosts()}
