# uffis-portal

Multi tenant [Tethys Platform](https://www.tethysplatform.org/) portal for UFFIS, running on AWS ECS
Fargate with RDS Postgres.

Tenants are isolated by Postgres schema (`django-tenants`) and routed by hostname. The portal is
served at `uffis.org` and each tenant at `<tenant>.uffis.org`, all from one Fargate service
behind one CloudFront distribution.

The image builds FROM the shared [`tethys-uvx`](https://github.com/Aquaveo/tethys-uvx) base. The
infrastructure is the shared [`tethys-ecs-iac`](https://github.com/Aquaveo/tethys-ecs-iac) OpenTofu
module. This repo holds only the UFFIS image, config, tenancy hooks, tfvars, and CI.

## Layout

```
Dockerfile                        FROM tethys-uvx builder + runtime-base, plus the app layer
pyproject.toml                    app layer dependencies (django-tenants, storages, boto3)
conf/portal_config.yml            declarative portal settings, including TENANTS_CONFIG
conf/portal-config.d/             config hooks, run by the base portal-config.sh at container start
conf/init.d/                      provisioning hooks, run by the base provision.sh once per release
conf/register_tenants.py          creates the public tenant and its domain rows
conf/portal_storage.py            S3 static storage backend
tofu/uffis.tfvars.example         infrastructure inputs, tokenized; the real file is gitignored
tofu/backend.hcl.example          tofu state location, tokenized
tofu-rds/                         the Postgres instance, applied once with admin credentials
tofu-iam/                         OIDC CI roles, applied once with admin credentials
.github/workflows/                build (image to ECR), tofu deploy, sync secrets to SSM
```

## How multi tenancy is wired

Nothing in `tethys-uvx` is modified. Everything runs through the base image extension points.

The wildcard host lives in `conf/portal_config.yml` directly. The base **appends** to
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` rather than replacing them, so the declared
`.uffis.org` and `https://*.uffis.org` survive its render. Note the three spellings: the
CloudFront alias in the tfvars is `*.uffis.org`, Django's host wildcard needs the leading dot,
and Django's CSRF origin needs the scheme and the asterisk.

`conf/portal-config.d/05-tenancy.sh` covers the two things config cannot:

1. It refuses to start when `TETHYS_DB_POOL_MODE` is not `direct`. That is the only runtime guard on
   the tenant isolation invariant, so it fails loudly rather than serving one tenant another's data.
2. It sets the database engine to `django_tenants.postgresql_backend`, then reads it back and fails
   if it did not stick. Unlike the host lists, the base **overwrites** this key from the
   `TETHYS_DB_ENGINE` task environment variable, so the `ENGINE` line in `portal_config.yml` is inert
   and the engine can only be set from a hook.

`conf/init.d/10-tenancy.sh` runs at the end of provisioning. It does **not** migrate: the base image's
`tethys db migrate` already covers every schema, because django-tenants shadows Django's `migrate`
command with `MigrateSchemasCommand`, which syncs public and all tenants when given no flag. Calling
`tethys manage migrate_schemas` afterwards would be a redundant second pass, and worse, the
`tethys manage` path discards the child exit code, so a failed tenant migration would report success.

The hook registers the public tenant's domain rows. Without them `django-tenants` has no Domain to
match and the portal 404s on its own hostname.

Two things are deliberately absent until the app layer lands. The Tethys harvester only ever writes
the app registry into the public schema, so a tenant's registry stays empty; and `tethys site -f`
runs once on public, so tenants render stock branding rather than the `site_settings` block. Both
need a per schema pass, and neither matters while the portal ships no apps.

`conf/register_tenants.py` carries the portal domain as a module constant rather than reading it
from the environment. The shared IaC module supplies no portal domain, so an environment read would
silently yield nothing and leave the portal 404ing on its own hostname.

`TENANT_APPS` lists six apps, not the two shown in the Tethys documentation. `tethys_apps` holds
foreign keys into `tethys_services` and `tethys_compute`, so a tenant schema cannot be built without
them. Omitting them makes `tethys manage create_tenant` fail while still exiting zero, leaving a half
built schema. Including `tethys_quotas` and `guardian` additionally keeps quotas, jobs, and object
permissions per tenant.

`db_pool_mode` must stay `direct`. `django-tenants` selects the active tenant with `SET search_path`
on the connection, so a transaction mode pooler such as Supavisor or PgBouncer will serve one tenant
a different tenant's data.

## One time setup

**No account identifiers are committed.** `tofu/uffis.tfvars` and the three `backend.hcl` files are
gitignored; the repo carries `.example` versions with `__TOKEN__` placeholders. The deploy workflow
renders the real files from repository variables at run time, and the lint workflow fails if an
account id, VPC or subnet ever lands in a tracked file.

For local work, copy each example and substitute:

```bash
sed "s/__STATE_BUCKET__/<bucket>/" tofu/backend.hcl.example > tofu/backend.hcl
```

Set these repository variables before the first deploy (Settings, Secrets and variables, Actions):
`AWS_REGION`, `ECR_REPOSITORY`, `TOFU_STATE_BUCKET`, `AWS_ACCOUNT_ID`, `VPC_ID`, `SUBNET_IDS`,
`ACM_CERTIFICATE_ARN`, `DB_HOST`, `PORTAL_DOMAIN`. `SUBNET_IDS` is a JSON array, for example
`["subnet-aaa", "subnet-bbb"]`.

The image tag is a workflow input rather than a committed value, so deploying a new build no longer
means editing and committing a tfvars file.

Two prerequisites need IAM permissions that `AWSPowerUserAccess` does not grant, so they need an
administrator: the GitHub OIDC identity provider (`iam:CreateOpenIDConnectProvider`), and the
`tofu-iam` apply, which creates the CI roles. Nothing in the CI path works until both exist.

### 1. Credentials

```bash
aws sso login --sso-session <your-sso-session>
export AWS_PROFILE=<your-admin-profile>
export AWS_REGION=us-east-1
aws sts get-caller-identity
eval "$(aws configure export-credentials --profile "$AWS_PROFILE" --format env)"
```

OpenTofu's AWS provider does not refresh SSO tokens, so the `export-credentials` line is required
even when the CLI itself works.

### 2. RDS

`tofu-rds/` is a separate root module with its own state key, so a `tofu destroy` of the portal
cannot reach the database. The instance also carries `deletion_protection = true` and takes a final
snapshot, so destroying it takes two deliberate steps.

```bash
cd tofu-rds
tofu init -backend-config=backend.hcl
export TF_VAR_master_password='<strong-password>'
tofu apply -var vpc_id=<vpc-id> -var 'subnet_ids=["<subnet-a>","<subnet-b>"]'
tofu output db_host
```

Put `db_host` in `tofu/uffis.tfvars`, and set the same password as the `DB_PASSWORD` GitHub secret in
step 5 so the running task and the instance agree.

`db_name` is created with the instance, so there is no separate `psql` step. That matters because the
instance is not publicly accessible and its only ingress will be the Fargate security group, so there
is no network path to it from a workstation.

**The database stays closed until step 6.** Its ingress source is the portal's web security group,
which does not exist until the first portal apply. Do not open it to a VPC CIDR to get moving; the
master credential is also the application credential.

The master password is stored in this module's state. The state bucket is versioned, encrypted and
access controlled, which is the usual accepted tradeoff. If you would rather it never touch state,
switch the instance to `manage_master_user_password = true` and have RDS generate it into Secrets
Manager, then copy it into SSM instead of setting the GitHub secret.

### 3. Certificate

The certificate must live in `us-east-1` in the account that runs the portal, because CloudFront only
reads certificates from there. The DNS validation record goes in the `uffis.org` hosted zone, which
is in the UFFIS account. Those may be two different accounts.

```bash
aws acm request-certificate --region us-east-1 \
  --domain-name uffis.org \
  --subject-alternative-names '*.uffis.org' \
  --validation-method DNS \
  --query CertificateArn --output text

aws acm describe-certificate --region us-east-1 --certificate-arn <arn> \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord'
```

ACM emits a single validation record for a name and its own wildcard, so expect one CNAME rather than
two. Create it in `uffis.org`, then wait:

```bash
aws acm wait certificate-validated --region us-east-1 --certificate-arn <arn>
```

Put the ARN in `tofu/uffis.tfvars` as `acm_certificate_arn`.

### 4. CI roles

```bash
cd tofu-iam
cp backend.hcl.example backend.hcl
cp uffis.tfvars.example uffis.tfvars
sed -i "s|__STATE_BUCKET__|<bucket>|;s|__GITHUB_ORG_ID__|$(gh api orgs/Aquaveo --jq .id)|;s|__GITHUB_REPO_ID__|$(gh api repos/Aquaveo/uffis-portal --jq .id)|" uffis.tfvars
tofu init -backend-config=backend.hcl
tofu apply -var-file=uffis.tfvars
tofu output ecr_role_arn
tofu output deploy_role_arn
tofu output ci_boundary_arn
```

Apply this once with admin credentials. It creates the role the deploy workflow assumes, so the
deploy workflow cannot create it. `uffis.tfvars` is gitignored and the tokenised `.example` is what
ships; the id variables carry no default, so a missing value fails the plan rather than quietly
trusting the wrong OIDC subject.

GitHub puts the org and repo immutable ids in the OIDC subject claim, so the trusted subject is
`Aquaveo@<org id>/uffis-portal@<repo id>`, not the plain name. A trust policy written the name only
way is refused with `Not authorized to perform sts:AssumeRoleWithWebIdentity`, and the build then
fails before it reaches Docker.

The two roles trust different OIDC subjects. The ECR push role accepts `refs/heads/main` and version
tags. The deploy role accepts only `environment:production`, so **create a GitHub Environment named
`production`** on the repo before running the deploy or sync secrets workflows, or the role will
refuse to be assumed. Add required reviewers to that environment if you want deploys gated on an
approval.

```bash
gh secret set AWS_ROLE_ARN        --repo Aquaveo/uffis-portal --body "<ecr_role_arn>"
gh secret set AWS_DEPLOY_ROLE_ARN --repo Aquaveo/uffis-portal --body "<deploy_role_arn>"
gh variable set AWS_REGION        --repo Aquaveo/uffis-portal --body us-east-1
gh variable set ECR_REPOSITORY    --repo Aquaveo/uffis-portal --body tethys-portal
```

### 5. Secrets

```bash
gh secret set DB_PASSWORD        --repo Aquaveo/uffis-portal --body '<strong-password>'
gh secret set PS_CONNECTION      --repo Aquaveo/uffis-portal --body '<postgis-conn-string>'
gh secret set SECRET_KEY         --repo Aquaveo/uffis-portal --body "$(openssl rand -base64 48)"
gh secret set SUPERUSER_PASSWORD --repo Aquaveo/uffis-portal --body '<admin-password>'

gh workflow run sync-secrets.yml --repo Aquaveo/uffis-portal
aws ssm get-parameters-by-path --path /uffis/portal --recursive \
  --query 'Parameters[].Name' --output table
```

### 6. First deploy

The database is closed until the portal apply exists. `tofu-rds` only opens port 5432 when
`web_security_group_id` names the Fargate web security group, and that group is created by the
portal apply, so the first deploy is two phased. Run the portal apply, take `web_security_group_id`
from its output, put it in `tofu-rds/uffis.tfvars` and apply `tofu-rds` again, then run provision.
Skipping the second apply leaves the web task crashlooping on `connection timed out` to RDS and the
provision task stuck in its database wait loop.

The provision wait is capped below the OIDC credential lifetime on purpose. The role session lasts
an hour, so a wait that also lasted an hour would always die in `ExpiredTokenException` before it
could report its own timeout.

```bash
gh workflow run build.yml --repo Aquaveo/uffis-portal
```

Set `image_uri` in `tofu/uffis.tfvars` to the tag the build pushed, commit, push, then:

```bash
gh workflow run tofu-deploy.yml --repo Aquaveo/uffis-portal -f action=plan
gh workflow run tofu-deploy.yml --repo Aquaveo/uffis-portal -f action=apply
```

The first apply's provision task is expected to fail on the database wait, because the RDS security
group still has no ingress. Open it with the web security group the apply just created, then apply
again:

```bash
IAC=../tethys-ecs-iac/tofu
tofu -chdir=$IAC init -reconfigure -backend-config="$PWD/tofu/backend.hcl"
WEB_SG=$(tofu -chdir=$IAC output -raw web_security_group)

tofu -chdir=tofu-rds apply -var vpc_id=<vpc-id> \
  -var 'subnet_ids=["<subnet-a>","<subnet-b>"]' \
  -var web_security_group_id="$WEB_SG"

gh workflow run tofu-deploy.yml --repo Aquaveo/uffis-portal -f action=apply
```

The `-reconfigure` is required. The shared module directory keeps whichever backend it was last
initialized against, which may belong to another portal.

### 7. DNS

```bash
tofu -chdir=$IAC output cloudfront_domain
tofu -chdir=$IAC output -raw ecs_cluster | grep -q uffis && echo "state OK"
```

Create two records in `uffis.org`, both A and AAAA alias records to the CloudFront distribution
(hosted zone ID `Z2FDTNDATAQYW2`):

```
uffis.org
*.uffis.org
```

Use alias records rather than CNAME. Because of the wildcard, adding a tenant later needs no DNS
change at all.

### 8. Create tenants

The public tenant is registered automatically during provisioning. Each real tenant is created once.

The schema name and the hostname follow different rules. Postgres allows underscores in an
identifier, hostnames do not, and Django validates the Host header against a regex with no
underscore in it, so an underscored subdomain raises DisallowedHost before ALLOWED_HOSTS is
consulted and tenancy turns that into a 404. Give the schema an underscore and the domain a hyphen.
Tenants are one label under the apex, so a tenant subdomain is covered by the `*.uffis.org`
certificate and needs no new certificate. A two label name such as
`antigua-barbuda.uhm.uffis.org` is **not** covered by that wildcard, which is why the original
layout was abandoned. Tenants: `abms` on `abms.uffis.org` for Antigua and Barbuda, `uhm` on
`uhm.uffis.org` for Haiti.

The apex cannot be a CNAME, DNS forbids it alongside the zone's NS and SOA records. Use a Route 53
A record with Alias enabled, targeting the CloudFront distribution; the CloudFront hosted zone id
is the fixed `Z2FDTNDATAQYW2`.

Two things make the obvious form of these commands fail silently. A `containerOverrides` command
replaces the container command, so `portal-config.sh` never runs and the tenancy guard rejects the
call. And `create_tenant_superuser` wraps Django's interactive `createsuperuser`, which prints
"skipped" and exits zero with no TTY. The `--noinput` spelling is consumed by the Tethys manage
parser, so only `--no-input` reaches Django.

```bash
IAC=../tethys-ecs-iac/tofu
CLUSTER=$(tofu -chdir=$IAC output -raw ecs_cluster)
TD=$(tofu -chdir=$IAC output -raw provision_task_definition)
WEB_SG=$(tofu -chdir=$IAC output -raw web_security_group)
SUBNETS=$(tofu -chdir=$IAC output -json service_subnets | jq -r 'join(",")')
NETCFG="awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$WEB_SG],assignPublicIp=ENABLED}"

run_provision () {
  TASK=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$TD" \
    --launch-type FARGATE --network-configuration "$NETCFG" \
    --overrides "{\"containerOverrides\":[{\"name\":\"provision\",\"command\":[\"bash\",\"-lc\",\"$1\"]}]}" \
    --query 'tasks[0].taskArn' --output text)
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK"
  aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
    --query "tasks[0].containers[?name=='provision'].exitCode | [0]" --output text
}

run_provision "/usr/local/bin/portal-config.sh && tethys manage create_tenant \
  --schema_name abms --name 'Antigua and Barbuda' \
  --domain-domain abms.uffis.org --domain-is_primary True"

run_provision "/usr/local/bin/portal-config.sh && DJANGO_SUPERUSER_PASSWORD='<pw>' \
  tethys manage create_tenant_superuser --schema abms \
  --no-input --username admin --email '<addr>'"
```

Always read the task log, never the exit code. `create_tenant` reports success even when the schema
migration failed.

A new tenant's app registry stays empty until the harvest hook runs again, so re-run the tofu deploy
workflow (or `provision.sh`) after creating tenants.

### 9. Persistent stores

Tethys names a store database after the app package and the setting only, so every tenant resolves
to the same database and the name cannot carry the tenant. The service row is per tenant but only
carries host, port, username and password, and neither `get_url` nor `get_engine` accepts
connection options, so the connecting Postgres role is the only place isolation can live.

`conf/provision_tenant_store.py` gives each tenant a role, a schema inside the store database, and a
`search_path` default set with `IN DATABASE`. It runs from the provision hook, before
`all_tenants_command syncstores`.

Two things make the obvious version of this silently wrong. A cluster wide `ALTER ROLE ... SET
search_path` names a schema that does not exist in the store database, and Postgres then falls back
to `public` with no error, so tenants share rows while looking isolated. And `SHOW search_path`
reports the setting rather than the resolved schema, so it agrees with you either way. The hook
asserts on `current_schema()` instead and fails the provision when it does not match.

The public tenant gets `portal_public`, not `public`. The `public` schema is the fallback Postgres
uses when a `search_path` entry is missing, so pointing the public tenant at it would mean a
misprovisioned tenant lands in real data rather than an empty schema.

`syncstores` exits 0 even when it fails, because `tethys manage` discards the subprocess return, so
the hook greps its output and fails the provision on any error line.

Media is isolated per tenant, static is not. Every object under `static/` is a framework or app
asset collected from an installed package, byte identical for every tenant and public read through
CloudFront, so isolating it would duplicate it per tenant and fragment the cache without creating a
boundary. Media is written by tenant users, so it is prefixed with the tenant schema by
`TenantMediaS3Storage`, which overrides `_normalize_name`, the one seam `_open`, `_save`, `delete`,
`exists`, `listdir`, `size` and `url` all pass through on django-storages 1.14.6.

Test store changes against a non superuser database owner. A stock Postgres container makes
`POSTGRES_USER` a superuser, which bypasses the membership check that `CREATE SCHEMA ...
AUTHORIZATION` needs, so a provisioner that works locally can still fail on a managed instance with
`must be able to SET ROLE`. Create the role with `createdb createrole` and no superuser bit, and own
the portal database with it, to match what RDS gives you.

Outside a request django_tenants leaves the connection on the public schema, so a management
command writes under `media/portal_public/`. That cannot reach a tenant's files, but a job that
means to write for a tenant has to enter `schema_context` itself.

### 10. Verify

```bash
curl -sSI https://uffis.org/
curl -sSI https://abms.uffis.org/
curl -sSI https://nope.uffis.org/
```

Expect 200, 200, 200. `SHOW_PUBLIC_IF_NO_TENANT_FOUND` is true, so an unregistered subdomain serves
the public portal rather than 404ing. A **400 or 404 anywhere here means something is broken**, which
is the point: under tenancy `TenantMainMiddleware` turns a DisallowedHost into a 404 as well, so
tolerating 404 at the load balancer would make a misconfigured portal look healthy.

## Day to day

New image: push to `main`, then bump `image_uri` in `tofu/uffis.tfvars` and run the tofu deploy
workflow with `plan`, review, then `apply`.

Module change: the deploy workflow pins `iac_ref` to a `tethys-ecs-iac` commit so the module cannot
move between a reviewed plan and an apply. Bump that default deliberately, the same way the
Dockerfile's base image tags are bumped.

Rotate a secret: update the GitHub secret and run the sync secrets workflow.

Base image change: after the `tethys-uvx` CI publishes, bump `BASE_BUILDER` and `BASE_TAG` in the
Dockerfile to the new short sha, then rebuild and deploy. The base is pinned to immutable per commit
tags so a build cannot pick up a partially published base.

## Adding the app layer

The first deployment ships no Tethys apps, so tenant routing can be proven before app behaviour is
introduced. To add apps, extend `pyproject.toml` and the builder stage of the Dockerfile the way
`enee-geoglows-portal` does, then redeploy. Apps also need a per schema registration pass before they
appear for tenants, since the Tethys harvester only writes the public schema.

Apps with persistent stores need care. The persistent store database name is derived from the app
package and the store name with no tenant component, so two tenants running the same app share one
PostGIS database.

## Plugins

`tgf_wmo_plugins` is installed in the builder stage, pinned to a commit, and exposes six
`intake.drivers` entry points that tethysdash discovers. It ships no `static` directory. That used
to break provisioning, because tethysdash called `os.listdir` on one without checking; fixed
upstream in `tethysapp-tethys_dash` #183 and the local workaround is gone. tethysdash is cloned
from its default branch unpinned, so the fix is present. Pinning tethysdash to a release older than
that fix brings the `FileNotFoundError` back.

tethysdash is pinned by commit in `TETHYSDASH_REF`, not cloned from a moving branch. A
`git clone --depth 1` of a branch is not cache safe: Docker cannot tell the remote moved, so the
layer is reused forever and the same portal commit can build two different images. That bit us
once, the CI build reused a cached clone from before the upstream fix and provisioning failed with
`FileNotFoundError` after the local workaround had been removed. Bump the pin deliberately to take
a tethysdash change.

The CI build uses the GitHub Actions layer cache, `cache-from` and `cache-to: type=gha`, so a
cached layer survives across runs and across runners. When rebuilding locally to pick up a
tethysdash change, bust both stages: `docker build --no-cache-filter builder,runtime`. Busting only
`builder` leaves the runtime stage's `COPY --from=builder` cached, so the image keeps the old
tethysdash and looks like the change did not land.

Four of the six get a thumbnail; the two `impact_layer` drivers report no PNG available and are
skipped from static collection. They are still registered and usable, they just have no icon.

## Tenant branding

`branding/<schema>/` holds a tenant's brand assets. They are served from the shared static bucket,
not from media, because Tethys renders `feature_N_image` through `{% static %}` with no absolute
URL escape hatch; only `brand_image` accepts a full URL. Static is shared across tenants by design
and these are public assets, so a tenant prefix inside it is enough.

```bash
aws s3 cp branding/abms/ s3://uffis-portal-static/static/tenants/abms/ \
  --recursive --content-type image/png
```

The settings then reference the path relative to static, for example
`tenants/abms/abms_logo.png`. `collectstatic` does not delete unknown keys, so uploads
survive later deploys.

`branding/hero/ocean-vortices.jpg` is the masthead photograph, shared by every tenant and tinted by
each one's brand colour. It is a NASA MODIS pass over the South Atlantic showing cloud vortices
shedding off an island, by Jeff Schmaltz of the MODIS Land Rapid Response Team at NASA GSFC, in the
public domain through Wikimedia Commons. It is deliberately not a photograph of any tenant's own
country and not a disaster scene: one image has to serve six agencies across the Caribbean, Central
America and the Indian Ocean without misrepresenting any of them.

Third party imagery is not reused beyond an agency's own mark. A partner site's photographs are
usually licensed stock, and emblems such as the Red Cross are protected independently of copyright,
so only the institution's own logo is rehosted and anything else is original work.

## Portal mail

Password reset needs an SMTP backend. Without one Django falls back to `localhost:25`, the send
raises `ConnectionRefusedError`, and the view still returns 302, so the user is told to check an
inbox that will never receive anything. That is worse than an error, because nobody reports it.

`conf/email_settings.py` builds the mail settings from the task environment. Tethys reads
`portal_config.yml` with a plain `yaml.safe_load` and reads nothing but `DJANGO_LOG_LEVEL` from the
environment, so an ECS secret has no way into settings on its own. The module closes that gap:
`TETHYS_PORTAL_CONFIG.ADDITIONAL_SETTINGS_FILES` names it and Tethys copies every name in its
`__all__` onto the settings module. With no `EMAIL_HOST` it exports nothing and Django keeps its
defaults. With `EMAIL_HOST` set but any of user, password or from address missing it raises and the
container fails at boot, because a half configured backend raises at send time and Django reports
that to the user as success.

Setup with SES in the portal account:

1. Verify the sender domain in SES and publish the DKIM records in the `uffis.org` zone, which is
   in another account.
2. Request production access. A new account is sandboxed, capped at 200 messages a day, and will
   only deliver to addresses you have individually verified, so reset mail to a real user fails
   until AWS grants it.
3. Create SMTP credentials in SES. They are not the same as an IAM access key, SES derives an SMTP
   password from it.
4. Set the `EMAIL_PASSWORD` GitHub secret, then run sync secrets. The parameter is optional, so an
   unset secret is skipped rather than failing the run.
5. Set `email_host`, `email_host_user` and `default_from_email` in the tofu vars and deploy.

The mail secret is only attached to the task when `email_host` is set. A `valueFrom` pointing at a
parameter that does not exist stops the task from starting at all.

Account creation is closed. `ENABLE_OPEN_SIGNUP` is false, so `/accounts/register/` redirects to the
login page on every tenant and the login page does not offer a sign up link. Accounts are created by
an operator with `create_tenant_superuser`. That makes working password reset more important, not
less, since there is no self service route back in.

It was open briefly and was closed again deliberately. Open registration with no captcha lets anyone
create an account, and since `auth_user` is a tenant table that account is scoped to the host it was
created on. The registration form itself sends no mail, but a registered address can then request a
password reset, which is the one way a stranger can make the portal send mail. Closing signup
removes that. The styled sign up template is still shipped and still correct, so the setting is the
only thing standing between here and self service.

Signing up would not have granted access to any app in any case. `ENABLE_RESTRICTED_APP_ACCESS` is
true, so `user_can_access_app` requires the object level `<package>:access_app` permission rather
than returning true for anyone logged in. A logged in account with no grant sees an empty apps
library and gets a 404 from `TethysAppAccessMiddleware` on an app URL.

Grant access per tenant, in that tenant's admin under Authentication and Authorization, Groups.
Creating or editing a group there offers the installed apps; ticking one assigns
`<package>:access_app` to the group, and members of the group inherit it. Superusers bypass the
check, because guardian short circuits them.

Both settings are portal wide, so they apply to every tenant or none, but app access grants are per
tenant because groups live in the tenant schema.

`DEFAULT_FROM_EMAIL` is portal wide, not per tenant, and SES only authorises the one verified
sender, so a reset leaves from the same address whichever subdomain requested it. `EMAIL_FROM` is
the display name in front of it and defaults to `UFFIS Portal`. Do not put a display name inside
`DEFAULT_FROM_EMAIL`: Tethys strips a trailing `>` from that value and would send a malformed
address, and `email_settings.py` refuses to boot on one rather than leave it to be remembered. The tenant identity is carried by the message instead: the reset body and subject name the
host that was asked and the link returns to that same host, because `django.contrib.sites` is not
installed and Django falls back to the request.

## Account pages

Every account page is themed per tenant with no site setting to configure.
`conf/portal_templates/tethys_portal/accounts/base.html` shadows the Tethys accounts base by name,
which works because `ADDITIONAL_TEMPLATE_DIRS` puts `portal_templates` ahead of the Tethys template
directory. It pulls in `uffis/_account.html`, which derives its colours from that tenant's site
settings. Login, sign up, password change and all four password reset pages inherit from it.

The login, sign up and password change forms declare their fields with `label=""` upstream, so the
stock pages render empty `<label>` elements and the inputs have no accessible name at all. The
shadows pass an explicit label to each field. Keep the shadows in step when Tethys changes its own
copies of these templates.

## TLS to the origin

TLS terminates at CloudFront. The hop to the ALB is plain HTTP, so without help the ALB sets
`X-Forwarded-Proto: http`, `request.is_secure()` is false, and every absolute URL Django builds is
`http://`, password reset links included. The link still works because the edge redirects, but the
single use token makes one plaintext trip.

CloudFront adds `X-Forwarded-Proto-Edge: https` to origin requests and `SECURE_PROXY_SSL_HEADER`
points at that instead. `X-Forwarded-Proto` cannot be used for this: the ALB sets it from its own
listener protocol, so a value from CloudFront is overwritten or appended to, and Django compares it
exactly.

That header is only believable because `restrict_alb_to_cloudfront` limits the listener to
CloudFront's origin-facing prefix list. A custom header is not overwritten by the ALB, so while the
world could reach port 80 the world could also send it. Enabling the header without the restriction
would be worse than leaving both off.

The restriction closes a second hole in its own right. The ALB was internet-facing on `0.0.0.0/0`
and the task's allowed hosts include the load balancer DNS name, so the whole portal answered in
plaintext at `http://<alb>.elb.amazonaws.com/` with a `Host` header selecting any tenant, bypassing
the redirect entirely.

## Known limits

Media is isolated per tenant but not private. `TenantMediaS3Storage` keys every object under the
tenant schema, so no tenant can read, overwrite or list another's uploads through the portal, and
two tenants can hold the same filename. The bucket is still served public read through CloudFront
with `querystring_auth` off, so anyone holding an object URL can fetch it without authenticating.
The prefix is a boundary between tenants, not access control against the internet. Do not upload
anything that must not be public.

The portal wide superuser cannot read tenant data through the admin, because authentication and
sessions are per tenant. It can administer tenant and domain rows, and so can repoint any tenant
hostname. Any principal with `ecs:RunTask` on the provision task definition, including the CI deploy
role, can create a superuser inside any tenant schema.

The ALB health check reaches the task with the task private IP as the Host header, which can never
have a domain row. Rather than widening the target group matcher to tolerate 404, the portal sets
`SHOW_PUBLIC_IF_NO_TENANT_FOUND: true` so that request legitimately returns 200 and the matcher stays
at `200-399`. The tradeoff is that a mistyped tenant subdomain serves the public portal instead of
404ing; the gain is that a 404 still means something is genuinely wrong.
