import asyncio
import logging
import os
from abc import ABC, abstractmethod

from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


_MAX_PATH_LENGTH = 512   # total characters in the raw input
_MAX_PATH_DEPTH = 10     # maximum number of directory levels


def sanitize_path(raw: str) -> str | None:
    """
    Sanitize a user-supplied save path into a safe relative key.

    - Rejects paths longer than _MAX_PATH_LENGTH chars.
    - Splits on '/' and applies secure_filename to each component.
    - Returns None if any component is empty after sanitization (catches '..', '.', etc.)
    - Rejects paths deeper than _MAX_PATH_DEPTH levels.
    - Safe for both local filesystem paths and S3 object keys.
    """
    if len(raw) > _MAX_PATH_LENGTH:
        return None

    parts = raw.replace("\\", "/").split("/")
    safe: list[str] = []
    for part in parts:
        if not part:
            continue
        cleaned = secure_filename(part)
        if not cleaned:
            return None  # '..' or '.' collapsed to empty → reject
        safe.append(cleaned)

    if len(safe) > _MAX_PATH_DEPTH:
        return None

    return "/".join(safe) if safe else None


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, data: bytes, key: str, mime_type: str) -> str:
        """Persist *data* at *key*. Returns a URL or relative path string."""


class LocalStorage(StorageBackend):
    def __init__(self, upload_folder: str) -> None:
        self.root = os.path.abspath(upload_folder)
        os.makedirs(self.root, exist_ok=True)

    async def save(self, data: bytes, key: str, mime_type: str) -> str:
        full = os.path.abspath(os.path.join(self.root, key))
        # Path-traversal guard
        if not full.startswith(self.root + os.sep):
            raise ValueError(f"Rejected path outside upload root: {key!r}")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._write, full, data)
        return key

    def _write(self, path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


class S3Storage(StorageBackend):
    """
    S3-compatible storage backend.

    Works with AWS S3 and DigitalOcean Spaces (pass the Spaces endpoint as
    S3_ENDPOINT_URL, e.g. https://nyc3.digitaloceanspaces.com).
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str,
        public_url: str = "",
    ) -> None:
        if not bucket:
            raise ValueError("S3_BUCKET must be set when using the S3 storage backend.")
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.public_url = public_url.rstrip("/")

    def _client_kwargs(self) -> dict:
        kwargs: dict = {
            "aws_access_key_id": self.access_key,
            "aws_secret_access_key": self.secret_key,
            "region_name": self.region,
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return kwargs

    def _object_url(self, key: str) -> str:
        if self.public_url:
            return f"{self.public_url}/{key}"
        if self.endpoint_url:
            return f"{self.endpoint_url.rstrip('/')}/{self.bucket}/{key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

    async def save(self, data: bytes, key: str, mime_type: str) -> str:
        import aioboto3  # lazy import — only required for S3 backend

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=mime_type,
                ServerSideEncryption="AES256",
            )
        return self._object_url(key)
