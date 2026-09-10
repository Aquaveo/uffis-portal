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
  type    = string
  default = "uffis-portal"
}

variable "cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "azs" {
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
  description = "Two availability zones. RDS subnet groups require at least two."
}

locals {
  public_cidrs  = [cidrsubnet(var.cidr, 4, 0), cidrsubnet(var.cidr, 4, 1)]
  private_cidrs = [cidrsubnet(var.cidr, 4, 8), cidrsubnet(var.cidr, 4, 9)]
  tags          = { project = var.name }
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.tags, { Name = var.name })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name}-igw" })
}

resource "aws_subnet" "public" {
  count                   = length(var.azs)
  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.azs[count.index]
  cidr_block              = local.public_cidrs[count.index]
  map_public_ip_on_launch = true
  tags                    = merge(local.tags, { Name = "${var.name}-public-${var.azs[count.index]}", tier = "public" })
}

resource "aws_subnet" "private" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.this.id
  availability_zone = var.azs[count.index]
  cidr_block        = local.private_cidrs[count.index]
  tags              = merge(local.tags, { Name = "${var.name}-private-${var.azs[count.index]}", tier = "private" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = merge(local.tags, { Name = "${var.name}-public" })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name}-private" })
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
  tags   = merge(local.tags, { Name = "${var.name}-default-closed" })
}

output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "ALB and Fargate tasks. Public so tasks reach ECR without a NAT gateway."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "RDS. No route to the internet."
  value       = aws_subnet.private[*].id
}
