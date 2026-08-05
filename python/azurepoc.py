#!/usr/bin/env python3
import argparse
import json
import sys

import requests
from azure.identity import ClientSecretCredential  # azure-identity[1][9]

ARM_SCOPE = "https://management.azure.com/.default"
POLICY_API_VERSION = "2021-06-01"  # common ARM policyDefinitions API version


def parse_args():
    parser = argparse.ArgumentParser(
        description="List Azure Policy Definitions using ClientSecretCredential and ARM REST API"
    )

    # Display/owner info (optional, just for completeness)
    parser.add_argument(
        "--user-name",
        default="Raymond Gregoire",
        help="Display name associated with the subscription/principal",
    )
    parser.add_argument(
        "--subscription-label",
        default="ACDJ-TVPG-BG7-PGB",
        help="Human-readable subscription label/name",
    )

    # Azure AD tenant / directory
    parser.add_argument(
        "--tenant-id",
        default="3070748c-044e-410f-88f5-0e4a1ab6055c",
        help="Azure AD tenant (Directory) ID",
    )

    # Service principal (app registration)
    parser.add_argument(
        "--client-id",
        default="2cf424da-d183-4884-ae4d-2038b6cbaddc",
        help="Application (client) ID of the service principal",
    )
    parser.add_argument(
        "--object-id",
        default="8c8136de-7775-45af-82fd-8e594c12d370",
        help="Object ID of the service principal (not used for auth, included for reference)",
    )

    # Client secret
    parser.add_argument(
        "--client-secret",
        default="qUp8Q~jWFb-Ey1uUbyCezWDfH8dSEZZZtU_XSazc",
        help="Client secret value for the application",
    )
    parser.add_argument(
        "--secret-id",
        default="98711d99-2371-4885-9b89-ba423eed66f8",
        help="Client secret ID (metadata, not used for auth)",
    )

    # Subscription ID (you should replace the default with your real subscription GUID)
    parser.add_argument(
        "--subscription-id",
        required=True,
        help="Azure subscription ID whose policy definitions will be listed",
    )

    return parser.parse_args()


def get_arm_token(tenant_id, client_id, client_secret):
    # Create the credential using client credentials[1][4][9]
    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )

    # Request an access token for Azure Resource Manager[4][7]
    token = credential.get_token(ARM_SCOPE)
    return token.token  # raw bearer token string


def list_subscription_policies(subscription_id, arm_token):
    # REST API URL for policy definitions at subscription scope
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}/"
        f"providers/Microsoft.Authorization/policyDefinitions"
        f"?api-version={POLICY_API_VERSION}"
    )

    headers = {
        "Authorization": f"Bearer {arm_token}",
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    return response.json()


def main():
    args = parse_args()

    print(f"Using tenant: {args.tenant_id}")
    print(f"Using client ID: {args.client_id}")
    print(f"Using subscription ID: {args.subscription_id}")

    try:
        arm_token = get_arm_token(args.tenant_id, args.client_id, args.client_secret)
    except Exception as e:
        print(f"Failed to acquire ARM access token: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        policies_json = list_subscription_policies(args.subscription_id, arm_token)
    except requests.HTTPError as e:
        print(f"HTTP error calling policyDefinitions API: {e}", file=sys.stderr)
        if e.response is not None:
            print(f"Response content: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error calling policyDefinitions API: {e}", file=sys.stderr)
        sys.exit(1)

    # Parse JSON response to get list of policies
    policies = policies_json.get("value", [])

    print(f"\nFound {len(policies)} policy definition(s):\n")
    for p in policies:
        name = p.get("name")
        display_name = p.get("properties", {}).get("displayName")
        policy_type = p.get("properties", {}).get("policyType")
        print(f"- name: {name}")
        print(f"  displayName: {display_name}")
        print(f"  policyType: {policy_type}")
        print()
        print()
        print()

    # If you want the raw JSON:
    # print(json.dumps(policies_json, indent=2))


if __name__ == "__main__":
    main()
