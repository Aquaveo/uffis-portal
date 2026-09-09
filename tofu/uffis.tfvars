org         = "uffis"
app         = "portal"
environment = "production"
region      = "us-east-1"

vpc_id          = "REPLACE_VPC_ID"
alb_subnets     = ["REPLACE_SUBNET_A", "REPLACE_SUBNET_B"]
service_subnets = ["REPLACE_SUBNET_A", "REPLACE_SUBNET_B"]

static_bucket_name    = "uffis-portal-static"
portal_domain         = "uhm.uffis.org"
portal_domain_aliases = ["*.uhm.uffis.org"]
acm_certificate_arn   = "REPLACE_ACM_CERT_ARN"

image_uri = "REPLACE_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/tethys-portal:uffis-REPLACE_SHA"

task_cpu      = "1024"
task_memory   = "4096"
desired_count = 1
asgi_processes = "1"
server        = "gunicorn"

db_host      = "REPLACE_RDS_ENDPOINT"
db_username  = "tethys_default"
db_name      = "tethys_platform"
db_port      = 5432
db_pool_mode = "direct"
