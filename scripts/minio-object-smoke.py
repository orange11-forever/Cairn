import os
import sys

import boto3
from botocore.config import Config


def main() -> None:
    endpoint_url = sys.argv[1]
    access_key = os.environ["CAIRN_OBJECT_STORE_ACCESS_KEY"]
    secret_key = os.environ["CAIRN_OBJECT_STORE_SECRET_KEY"]
    bucket = "cairn-minio-smoke"
    object_key = "fresh-volume/round-trip.txt"
    expected = b"cairn-minio-round-trip"

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    client.create_bucket(Bucket=bucket)
    client.put_object(Bucket=bucket, Key=object_key, Body=expected)
    response = client.get_object(Bucket=bucket, Key=object_key)
    actual = response["Body"].read()
    response["Body"].close()
    if actual != expected:
        raise RuntimeError(f"MinIO object round trip mismatch: {actual!r}")


if __name__ == "__main__":
    main()
