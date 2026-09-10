
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}
variable "github_org" {
  type    = string
  default = "Aquaveo"
}
variable "github_repo" {
  type    = string
  default = "uffis-portal"
}
variable "ecr_repository" {
  type    = string
  default = "tethys-portal"
}
variable "state_bucket" {
  type        = string
  description = "Tofu state bucket. Supply with TF_VAR_state_bucket so it is not committed."
}

data "aws_caller_identity" "me" {}

locals {
  account           = data.aws_caller_identity.me.account_id
  oidc_provider_arn = "arn:aws:iam::${local.account}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "assume_ecr" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main",
        "repo:${var.github_org}/${var.github_repo}:ref:refs/tags/*",
      ]
    }
  }
}

data "aws_iam_policy_document" "assume_deploy" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:environment:production"]
    }
  }
}

resource "aws_iam_role" "ecr" {
  name               = "${var.github_repo}-ci-ecr"
  assume_role_policy = data.aws_iam_policy_document.assume_ecr.json
}

data "aws_iam_policy_document" "ecr_push" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage",
    ]
    resources = ["arn:aws:ecr:${var.region}:${local.account}:repository/${var.ecr_repository}"]
  }
}

resource "aws_iam_role_policy" "ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.ecr.id
  policy = data.aws_iam_policy_document.ecr_push.json
}

resource "aws_iam_role" "deploy" {
  name               = "${var.github_repo}-tofu-deploy"
  assume_role_policy = data.aws_iam_policy_document.assume_deploy.json
}

resource "aws_iam_role_policy_attachment" "deploy_poweruser" {
  role       = aws_iam_role.deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "deploy_iam" {
  statement {
    sid = "ManagePortalRoles"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
      "iam:ListRolePolicies", "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
    ]
    resources = ["arn:aws:iam::${local.account}:role/${var.github_repo}-*"]
  }

  statement {
    sid       = "AttachOnlyTheEcsExecutionPolicy"
    actions   = ["iam:AttachRolePolicy"]
    resources = ["arn:aws:iam::${local.account}:role/${var.github_repo}-*"]
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = ["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]
    }
  }

  statement {
    sid       = "PassPortalRolesToEcsOnly"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account}:role/${var.github_repo}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy_iam" {
  name   = "iam-role-management"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_iam.json
}

data "aws_iam_policy_document" "deploy_state" {
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketVersioning"]
    resources = ["arn:aws:s3:::${var.state_bucket}"]
  }
  statement {
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}.tfstate",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}.tfstate.tflock",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}-iam.tfstate",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}-iam.tfstate.tflock",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}-rds.tfstate",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}-vpc.tfstate",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}-vpc.tfstate.tflock",
      "arn:aws:s3:::${var.state_bucket}/portals/${var.github_repo}-rds.tfstate.tflock",
    ]
  }
}

resource "aws_iam_role_policy" "deploy_state" {
  name   = "tofu-state"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_state.json
}

output "ecr_role_arn" {
  description = "Set as the GitHub repo secret AWS_ROLE_ARN (build.yml)."
  value       = aws_iam_role.ecr.arn
}
output "deploy_role_arn" {
  description = "Set as the GitHub repo secret AWS_DEPLOY_ROLE_ARN (tofu-deploy.yml + sync-secrets.yml)."
  value       = aws_iam_role.deploy.arn
}
