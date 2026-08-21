from pathlib import Path, PurePosixPath

import boto3

from app.core.config import settings


# Where local-disk uploads live, resolved from this file rather than the
# process CWD. A relative path would put the uploads under a different
# directory depending on whether the server was started from the repo root or
# from server/, and api/extract.py reads the same tree by absolute path — so
# the two would disagree about where a document is.
UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "server" / "data" / "uploads"


def use_object_storage() -> bool:
    return bool(settings.r2_endpoint_url and settings.r2_access_key_id and settings.r2_secret_access_key)


def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
    )


def local_path(object_key: str) -> Path:
    """Resolve an object key to a path that cannot escape the upload root.

    Keys are built server-side, but this is the one place a stored string turns
    into a filesystem path, so it is checked here rather than trusted.
    """
    candidate = (UPLOAD_ROOT / PurePosixPath(object_key)).resolve()
    root = UPLOAD_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Object key '{object_key}' resolves outside the upload root.")
    return candidate


def upload_bytes(object_key: str, content: bytes, content_type: str) -> str:
    if not use_object_storage():
        path = local_path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    client = r2_client()
    client.put_object(Bucket=settings.r2_bucket, Key=object_key, Body=content, ContentType=content_type)
    return object_key


def read_bytes(object_key: str) -> bytes:
    """Read back a previously stored object (local disk or R2)."""
    if not use_object_storage():
        path = local_path(object_key)
        if not path.exists():
            # Older uploads may already store the full local path as the key.
            legacy = Path(object_key)
            if legacy.is_file():
                return legacy.read_bytes()
        return path.read_bytes()

    client = r2_client()
    response = client.get_object(Bucket=settings.r2_bucket, Key=object_key)
    return response["Body"].read()


def delete_object(object_key: str) -> None:
    """Remove a stored object. Missing is success — the goal is that it is gone.

    Never raises: it is called after the database rows are already committed,
    where a storage error must not turn a completed delete into a failed
    request.
    """
    if not object_key:
        return
    try:
        if not use_object_storage():
            path = local_path(object_key)
            path.unlink(missing_ok=True)
            # The extraction sidecar written next to the document goes too.
            path.with_name(f"{path.stem}_extracted.json").unlink(missing_ok=True)
            return
        r2_client().delete_object(Bucket=settings.r2_bucket, Key=object_key)
    except (OSError, ValueError) as exc:
        print(f"[storage] could not delete '{object_key}': {exc}")
    except Exception as exc:  # noqa: BLE001 - a boto3/network failure must not fail the request
        print(f"[storage] could not delete '{object_key}': {exc}")
