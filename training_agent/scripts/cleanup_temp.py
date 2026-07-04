"""Cleanup temporary chat attachments from MinIO.

Deletes objects under temp_attachments/ prefix older than 24 hours.

Usage:
    python scripts/cleanup_temp.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings


def cleanup_temp_attachments(max_age_hours: int = 24) -> int:
    """Delete temp attachments older than max_age_hours.

    Returns:
        Number of objects deleted
    """
    from minio import Minio

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )

    if not client.bucket_exists(settings.minio_bucket):
        print(f"Bucket '{settings.minio_bucket}' does not exist.")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    prefix = f"{settings.temp_attachment_prefix}/"
    deleted = 0

    objects = client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)
    for obj in objects:
        if obj.last_modified and obj.last_modified < cutoff:
            try:
                client.remove_object(settings.minio_bucket, obj.object_name)
                deleted += 1
                print(f"Deleted: {obj.object_name}")
            except Exception as e:
                print(f"Failed to delete {obj.object_name}: {e}")

    print(f"Cleanup complete. Deleted {deleted} objects older than {max_age_hours}h.")
    return deleted


if __name__ == "__main__":
    cleanup_temp_attachments()
