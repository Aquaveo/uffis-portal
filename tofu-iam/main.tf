
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
variable "github_org_id" {
  type        = number
  description = "GitHub sends the org and repo immutable ids in the OIDC sub claim. Pinning them survives a rename and stops a deleted and recreated repo of the same name from assuming these roles. No default, so a missing value fails the plan rather than silently trusting the wrong subject."
}

variable "github_repo_id" {
  type = number
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
        "repo:${local.gh_repo}:ref:refs/heads/main",
        "repo:${local.gh_repo}:ref:refs/tags/*",
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
      values   = ["repo:${local.gh_repo}:environment:production"]
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

data "aws_iam_policy_document" "ci_boundary" {
  statement {
    effect      = "Allow"
    not_actions = ["iam:*", "organizations:*", "account:*", "sts:AssumeRole"]
    resources   = ["*"]
  }
}

resource "aws_iam_policy" "ci_boundary" {
  name        = "${var.github_repo}-ci-boundary"
  description = "Ceiling for roles the deploy role creates. Denies IAM, Organizations, account and AssumeRole."
  policy      = data.aws_iam_policy_document.ci_boundary.json
}

locals {
  gh_repo = "${var.github_org}@${var.github_org_id}/${var.github_repo}@${var.github_repo_id}"

  managed_roles = [
    "arn:aws:iam::${local.account}:role/${var.github_repo}-exec",
    "arn:aws:iam::${local.account}:role/${var.github_repo}-task",
  ]
}

data "aws_iam_policy_document" "deploy_iam" {
  statement {
    sid       = "ReadPortalRoles"
    actions   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole"]
    resources = ["arn:aws:iam::${local.account}:role/${var.github_repo}-*"]
  }

  statement {
    sid       = "CreatePortalRolesUnderBoundary"
    actions   = ["iam:CreateRole"]
    resources = local.managed_roles
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.ci_boundary.arn]
    }
  }

  statement {
    sid       = "SetTheBoundaryOnPortalRoles"
    actions   = ["iam:PutRolePermissionsBoundary"]
    resources = local.managed_roles
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.ci_boundary.arn]
    }
  }

  statement {
    sid       = "ManageBoundedPortalRoles"
    actions   = ["iam:DeleteRole", "iam:TagRole", "iam:UntagRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:DetachRolePolicy"]
    resources = local.managed_roles
  }

  statement {
    sid       = "AttachOnlyTheEcsExecutionPolicy"
    actions   = ["iam:AttachRolePolicy"]
    resources = local.managed_roles
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = ["arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"]
    }
  }

  statement {
    sid       = "PassPortalRolesToEcsOnly"
    actions   = ["iam:PassRole"]
    resources = local.managed_roles
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

output "ci_boundary_arn" {
  description = "Pass as iam_permissions_boundary in the portal tfvars."
  value       = aws_iam_policy.ci_boundary.arn
}
output "ecr_role_arn" {
  description = "Set as the GitHub repo secret AWS_ROLE_ARN (build.yml)."
  value       = aws_iam_role.ecr.arn
}
output "deploy_role_arn" {
  description = "Set as the GitHub repo secret AWS_DEPLOY_ROLE_ARN (tofu-deploy.yml + sync-secrets.yml)."
  value       = aws_iam_role.deploy.arn
}
