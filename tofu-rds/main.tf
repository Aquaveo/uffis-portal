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

variable "name" {
  type        = string
  default     = "uffis-portal"
  description = "Resource name prefix. Matches the portal repo and the tofu org/app pair."
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Two or more private subnets in different availability zones."
}

variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "engine_version" {
  type    = string
  default = "17"
}

variable "allocated_storage" {
  type    = number
  default = 50
}

variable "db_name" {
  type        = string
  default     = "tethys_platform"
  description = "Created at provision time so no operator to VPC network path is needed."
}

variable "master_username" {
  type    = string
  default = "tethys_default"
}

variable "master_password" {
  type        = string
  sensitive   = true
  description = "Supply with TF_VAR_master_password. Lands in state, see the README."
}

variable "backup_retention_period" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "web_security_group_id" {
  type        = string
  default     = ""
  description = "Fargate web security group, created by the portal apply. Empty leaves the database closed."
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db-subnets"
  subnet_ids = var.subnet_ids
  tags       = { project = var.name }
}

resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "${var.name} Postgres"
  vpc_id      = var.vpc_id
  tags        = { project = var.name, Name = "${var.name}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "from_web" {
  count                        = var.web_security_group_id == "" ? 0 : 1
  security_group_id            = aws_security_group.db.id
  description                  = "Postgres from the portal Fargate tasks"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = var.web_security_group_id
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.master_username
  password = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  backup_retention_period = var.backup_retention_period
  deletion_protection     = var.deletion_protection

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-db-final"

  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = { project = var.name }
}

output "db_host" {
  description = "Set as db_host in tofu/uffis.tfvars."
  value       = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "db_security_group_id" {
  value = aws_security_group.db.id
}
