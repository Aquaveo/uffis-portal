"""Render docs/architecture.png. Needs Graphviz and the diagrams package:

    docker run --rm -v "$PWD/docs:/docs" -w /docs python:3.12-slim sh -c \
      "apt-get update -qq && apt-get install -qq -y graphviz >/dev/null && pip -q install diagrams && python architecture.py"
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Fargate
from diagrams.aws.database import RDS
from diagrams.aws.engagement import SimpleEmailServiceSes
from diagrams.aws.management import SystemsManagerParameterStore
from diagrams.aws.network import ALB, CloudFront, Route53
from diagrams.aws.security import IAMRole
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import Users

graph = {"pad": "0.4", "nodesep": "0.6", "ranksep": "1.0", "splines": "spline"}

with Diagram("", filename="architecture", show=False, direction="LR", graph_attr=graph):
    users = Users("visitors")
    ci = GithubActions("GitHub Actions")

    with Cluster("AWS us-east-1"):
        dns = Route53("uffis.org\n*.uffis.org")
        cdn = CloudFront("CloudFront")
        alb = ALB("ALB\norigin.uffis.org")
        assets = S3("static + media")

        with Cluster("ECS Fargate"):
            web = Fargate("web")
            provision = Fargate("provision\n(once per release)")

        db = RDS("Postgres\none schema per tenant")
        ses = SimpleEmailServiceSes("SES")
        roles = IAMRole("OIDC roles")
        ecr = ECR("ECR")
        ssm = SystemsManagerParameterStore("SSM secrets")
        state = S3("tofu state")

    users >> dns >> cdn >> Edge(label="HTTPS") >> alb >> web >> db
    cdn >> assets
    web >> ses
    provision >> db

    ci >> Edge(label="OIDC") >> roles >> [ecr, ssm, state]
    ecr >> Edge(style="dashed") >> provision
    ssm >> Edge(style="dashed") >> provision
