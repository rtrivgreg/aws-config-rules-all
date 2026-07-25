terraform {
  required_version = ">= 1.5.0"

  cloud {
    organization = "RSHL2136"
    workspaces {
      name = "config-rules-all"
    }
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
