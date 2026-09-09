# uffis-portal

Multi tenant [Tethys Platform](https://www.tethysplatform.org/) portal for UFFIS, running on AWS ECS
Fargate with RDS Postgres.

Tenants are isolated by Postgres schema (`django-tenants`) and routed by hostname. The portal is
served at `uhm.uffis.org` and each tenant at `<tenant>.uhm.uffis.org`, all from one Fargate service
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
tofu/uffis.tfvars                 infrastructure inputs for the tethys-ecs-iac module
tofu/backend.hcl                  tofu state location, key portals/uffis-portal.tfstate
tofu-rds/                         the Postgres instance, applied once with admin credentials
tofu-iam/                         OIDC CI roles, applied once with admin credentials
.github/workflows/                build (image to ECR), tofu deploy, sync secrets to SSM
```

## How multi tenancy is wired

Nothing in `tethys-uvx` is modified. Everything runs through the base image extension points.

The wildcard host lives in `conf/portal_config.yml` directly. The base **appends** to
`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` rather than replacing them, so the declared
`.uhm.uffis.org` and `https://*.uhm.uffis.org` survive its render. Note the three spellings: the
CloudFront alias in the tfvars is `*.uhm.uffis.org`, Django's host wildcard needs the leading dot,
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

Values marked `REPLACE_` in `tofu/uffis.tfvars`, `tofu/backend.hcl`, and `tofu-iam/backend.hcl` must
be filled in before anything will apply.

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

#### Backups and snapshots

Automated backups run daily with seven day retention, in the `backup_window` (UTC, chosen to sit
outside Honduras business hours). Destroying the instance takes a final snapshot, and
`deletion_protection` means it refuses to be destroyed until that is turned off deliberately.

Before a risky change, take a named snapshot by setting `manual_snapshot_id`:

```bash
tofu -chdir=tofu-rds apply -var vpc_id=<vpc-id> \
  -var 'subnet_ids=["<subnet-a>","<subnet-b>"]' \
  -var manual_snapshot_id=pre-tenant-migration
```

**Changing that value replaces the snapshot, which deletes the previous one.** It holds one named
snapshot at a time, not a history. The daily automated backups are the history.

This is a deliberate operator action owned by whoever owns `tofu-rds/`, not something the deploy
pipeline does. A per deploy automatic snapshot would need a step in `tofu-deploy.yml` before the
provision task, since a declarative resource cannot take a fresh snapshot per release. That is worth
adding once tenant count makes a failed `migrate_schemas` expensive to unwind.

### 3. Certificate

The certificate must live in `us-east-1` in the account that runs the portal, because CloudFront only
reads certificates from there. The DNS validation record goes in the `uffis.org` hosted zone, which
is in the UFFIS account. Those may be two different accounts.

```bash
aws acm request-certificate --region us-east-1 \
  --domain-name uhm.uffis.org \
  --subject-alternative-names '*.uhm.uffis.org' \
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
tofu init -backend-config=backend.hcl
tofu apply
tofu output ecr_role_arn
tofu output deploy_role_arn
```

Apply this once with admin credentials. It creates the role the deploy workflow assumes, so the
deploy workflow cannot create it.

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
uhm.uffis.org
*.uhm.uffis.org
```

Use alias records rather than CNAME. Because of the wildcard, adding a tenant later needs no DNS
change at all.

### 8. Create tenants

The public tenant is registered automatically during provisioning. Each real tenant is created once.

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
  --schema_name <tenant> --name '<Tenant Name>' \
  --domain-domain <tenant>.uhm.uffis.org --domain-is_primary True"

run_provision "/usr/local/bin/portal-config.sh && DJANGO_SUPERUSER_PASSWORD='<pw>' \
  tethys manage create_tenant_superuser --schema <tenant> \
  --no-input --username admin --email '<addr>'"
```

Always read the task log, never the exit code. `create_tenant` reports success even when the schema
migration failed.

A new tenant's app registry stays empty until the harvest hook runs again, so re-run the tofu deploy
workflow (or `provision.sh`) after creating tenants.

### 9. Verify

```bash
curl -sSI https://uhm.uffis.org/
curl -sSI https://<tenant>.uhm.uffis.org/
curl -sSI https://nope.uhm.uffis.org/
```

Expect 200, 200, 200. `SHOW_PUBLIC_IF_NO_TENANT_FOUND` is true, so an unregistered subdomain serves
the public portal rather than 404ing. A **400 or 404 anywhere here means something is broken**, which
is the point: under tenancy `TenantMainMiddleware` turns a DisallowedHost into a 404 as well, so
tolerating 404 at the load balancer would make a misconfigured portal look healthy.

## Day to day

New image: push to `main`, then bump `image_uri` in `tofu/uffis.tfvars` and run the tofu deploy
workflow with `plan`, review, then `apply`.

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

## Known limits

Media is not isolated per tenant. All tenants share one S3 bucket and one `media/` prefix served
publicly through CloudFront, so any tenant's uploads are readable from any tenant hostname. Do not
upload non public data until per tenant prefixes are added.

The portal wide superuser cannot read tenant data through the admin, because authentication and
sessions are per tenant. It can administer tenant and domain rows, and so can repoint any tenant
hostname. Any principal with `ecs:RunTask` on the provision task definition, including the CI deploy
role, can create a superuser inside any tenant schema.

The ALB health check reaches the task with the task private IP as the Host header, which can never
have a domain row. Rather than widening the target group matcher to tolerate 404, the portal sets
`SHOW_PUBLIC_IF_NO_TENANT_FOUND: true` so that request legitimately returns 200 and the matcher stays
at `200-399`. The tradeoff is that a mistyped tenant subdomain serves the public portal instead of
404ing; the gain is that a 404 still means something is genuinely wrong.
