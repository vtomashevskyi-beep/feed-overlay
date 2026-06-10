"""
Збереження готових зображень і формування публічного URL.
Два бекенди:
  - local: пише в MEDIA_DIR, посилання формується від PUBLIC_BASE_URL (для дев/тесту)
  - s3:    будь-який S3-сумісний (AWS S3, Cloudflare R2, Backblaze B2, DO Spaces)

Налаштовується через env:
  STORAGE_BACKEND=local|s3
  PUBLIC_BASE_URL=https://your-domain.com        (local)
  S3_ENDPOINT_URL=https://<acc>.r2.cloudflarestorage.com  (для R2/B2; для AWS лишити пустим)
  S3_BUCKET=feed-images
  S3_PUBLIC_BASE=https://cdn.your-domain.com     (публічний домен бакета/CDN)
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
"""
from __future__ import annotations

import os
from pathlib import Path


class LocalStorage:
    def __init__(self):
        self.media_dir = Path(os.environ.get("MEDIA_DIR", "media"))
        self.media_dir.mkdir(parents=True, exist_ok=True)
        base = os.environ.get("PUBLIC_BASE_URL", "")
        if not base and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
            base = "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
        self.base_url = (base or "http://localhost:8000").rstrip("/")

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        path = self.media_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{self.base_url}/media/{key}"


class S3Storage:
    def __init__(self):
        import boto3
        endpoint = os.environ.get("S3_ENDPOINT_URL") or None
        self.bucket = os.environ["S3_BUCKET"]
        self.public_base = os.environ.get("S3_PUBLIC_BASE", "").rstrip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint)

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data,
            ContentType=content_type, CacheControl="public, max-age=31536000",
        )
        if self.public_base:
            return f"{self.public_base}/{key}"
        return f"https://{self.bucket}.s3.amazonaws.com/{key}"


def get_storage():
    backend = os.environ.get("STORAGE_BACKEND", "local").lower()
    if backend == "s3":
        return S3Storage()
    return LocalStorage()
