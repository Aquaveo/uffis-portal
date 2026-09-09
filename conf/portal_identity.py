"""Single source of truth for this portal's own hostnames.

These are portal owned constants, not deployment inputs. The shared IaC module does not supply them,
so reading them from the environment would silently yield nothing. Keep PORTAL_DOMAIN in step with
portal_domain in tofu/uffis.tfvars.
"""

PORTAL_DOMAIN = "uhm.uffis.org"

TENANT_WILDCARD = "*." + PORTAL_DOMAIN
