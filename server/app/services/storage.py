import boto3
from pathlib import Path

from app.core.config import settings


def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
    )


def upload_bytes(object_key: str, content: bytes, content_type: str) -> str:
    if not settings.r2_endpoint_url or not settings.r2_access_key_id or not settings.r2_secret_access_key:
        local_path = Path("server/data/uploads") / object_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        return str(local_path)

    client = r2_client()
    client.put_object(Bucket=settings.r2_bucket, Key=object_key, Body=content, ContentType=content_type)
    return object_key


def read_bytes(object_key: str) -> bytes:
    """Read back a previously stored object (local disk or R2)."""
    if not settings.r2_endpoint_url or not settings.r2_access_key_id or not settings.r2_secret_access_key:
        local_path = Path("server/data/uploads") / object_key
        if not local_path.exists():
            # Older uploads may already store the full local path as the key.
            local_path = Path(object_key)
        return local_path.read_bytes()

    client = r2_client()
    response = client.get_object(Bucket=settings.r2_bucket, Key=object_key)
    return response["Body"].read()
