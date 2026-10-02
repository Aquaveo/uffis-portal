"""Apps that serve the public schema only, never a tenant."""

APEX_APP = "uffis_forecasts"
APEX_APP_ROOT = "uffis_viewer/"
APEX_ONLY_APPS = (APEX_APP,)
APEX_APP_PATHS = (f"/apps/{APEX_APP.replace('_', '-')}/",)
