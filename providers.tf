provider "aws" {
  region = "us-east-1"
  # No credentials here — TFC OIDC via TFC_AWS_PROVIDER_AUTH
  # and TFC_AWS_RUN_ROLE_ARN handles all authentication
}
