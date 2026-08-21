import sys
import time
import pathlib

import boto3
from botocore.exceptions import ClientError

POLL_INTERVAL_SECONDS = 10


def load_template(path: str) -> str:
    p = pathlib.Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Template file not found: {path}")
    return p.read_text(encoding="utf-8")


def wait_for_conformance_pack_created(client, name: str):
    """Poll describe_conformance_pack_status until CREATE_COMPLETE or CREATE_FAILED."""
    start = time.time()

    while True:
        try:
            resp = client.describe_conformance_pack_status(
                ConformancePackNames=[name]
            )
        except ClientError as e:
            # If not found yet right after put, just wait and retry
            code = e.response["Error"]["Code"]
            if code == "NoSuchConformancePackException":
                print("Conformance pack status not yet available, waiting...")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            raise

        details = resp.get("ConformancePackStatusDetails", [])
        if not details:
            print("Conformance pack status empty, waiting...")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        status = details[0]
        state = status.get("ConformancePackState")
        reason = status.get("ConformancePackStatusReason") or ""
        print(f"Current state: {state} {('- ' + reason) if reason else ''}")

        # States documented by AWS Config: CREATE_IN_PROGRESS, CREATE_COMPLETE,
        # CREATE_FAILED, DELETE_IN_PROGRESS, DELETE_FAILED. [web:79][web:74]
        if state == "CREATE_IN_PROGRESS":
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        elif state == "CREATE_COMPLETE":
            break
        elif state == "CREATE_FAILED":
            raise RuntimeError(f"Conformance pack deployment failed: {reason}")
        elif state in ("DELETE_IN_PROGRESS", "DELETE_FAILED"):
            raise RuntimeError(f"Conformance pack is in unexpected delete state: {state}")
        else:
            # Unknown state, wait but surface it
            time.sleep(POLL_INTERVAL_SECONDS)

    end = time.time()
    elapsed = end - start
    return end, elapsed


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <conformance-pack-name> <template-file-path>")
        sys.exit(1)

    name = sys.argv[1]
    template_path = sys.argv[2]

    template_body = load_template(template_path)

    client = boto3.client("config")

    print(f"Deploying conformance pack '{name}' from template file '{template_path}'")

    try:
        # You must specify exactly one of TemplateBody, TemplateS3Uri,
        # or TemplateSSMDocumentDetails; here we use TemplateBody with the
        # local file contents. [web:75][web:76][web:80]
        resp = client.put_conformance_pack(
            ConformancePackName=name,
            TemplateBody=template_body,
        )
        arn = resp.get("ConformancePackArn")
        print(f"PutConformancePack initiated, ARN: {arn}")
    except ClientError as e:
        print(f"Failed to initiate conformance pack deployment: {e}")
        sys.exit(1)

    # After put_conformance_pack, AWS tracks deployment via
    # describe_conformance_pack_status and sets ConformancePackState values. [web:79][web:74][web:82]
    finished_at, elapsed = wait_for_conformance_pack_created(client, name)

    finished_str = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(finished_at))
    print(f"Deployment completed at: {finished_str}")
    print(f"Total time to deploy: {elapsed:.1f} seconds")


if __name__ == "__main__":
    main()
