import os


class Config:
    # Logging — empty string disables file logging (recommended for K8s)
    LOG_FOLDER: str = os.environ.get("LOG_FOLDER", "/app/logs")

    # Local storage (used when STORAGE_BACKEND=local)
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "/app/uploads")

    # Token management
    TOKEN_FILE_PATH: str = os.environ.get("TOKEN_FILE_PATH", "/app/config/tokens.txt")
    MASTER_TOKEN: str = os.environ.get("MASTER_TOKEN", "")
    TOKEN_RELOAD_INTERVAL: int = int(os.environ.get("TOKEN_RELOAD_INTERVAL", "10"))

    # Storage backend: "local" or "s3"
    STORAGE_BACKEND: str = os.environ.get("STORAGE_BACKEND", "local")

    # S3 / DigitalOcean Spaces config
    # For Spaces set S3_ENDPOINT_URL=https://<region>.digitaloceanspaces.com
    S3_BUCKET: str = os.environ.get("S3_BUCKET", "")
    S3_ENDPOINT_URL: str = os.environ.get("S3_ENDPOINT_URL", "")
    S3_ACCESS_KEY: str = os.environ.get("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.environ.get("S3_SECRET_KEY", "")
    S3_REGION: str = os.environ.get("S3_REGION", "us-east-1")
    # Optional CDN / public base URL (e.g. https://cdn.example.com)
    S3_PUBLIC_URL: str = os.environ.get("S3_PUBLIC_URL", "")

    # Upload constraints
    MAX_FILE_SIZE: int = int(os.environ.get("MAX_FILE_SIZE", str(10 * 1024 * 1024)))  # 10 MB
    ALLOWED_MIME_TYPES: frozenset = frozenset(
        t.strip()
        for t in os.environ.get("ALLOWED_MIME_TYPES", "image/jpeg,image/png").split(",")
        if t.strip()  # guard against empty string from ALLOWED_MIME_TYPES=""
    )

    # Rate limiting (slowapi format: "60/minute", "10/second", etc.)
    RATE_LIMIT: str = os.environ.get("RATE_LIMIT", "60/minute")

    # Comma-separated IPs or CIDRs of trusted reverse proxies.
    # X-Forwarded-For is only accepted from these addresses.
    # Empty = ignore XFF entirely and use the raw TCP connection IP.
    # Example: "10.0.0.0/8,172.16.0.0/12"
    TRUSTED_PROXIES: str = os.environ.get("TRUSTED_PROXIES", "")

    @classmethod
    def validate(cls) -> None:
        """Raise ValueError if any config value is invalid. Call at startup."""
        errors = []
        if cls.TOKEN_RELOAD_INTERVAL < 1:
            errors.append(f"TOKEN_RELOAD_INTERVAL must be >= 1, got {cls.TOKEN_RELOAD_INTERVAL}")
        if not cls.ALLOWED_MIME_TYPES:
            errors.append("ALLOWED_MIME_TYPES must not be empty")
        if cls.MAX_FILE_SIZE <= 0:
            errors.append(f"MAX_FILE_SIZE must be > 0, got {cls.MAX_FILE_SIZE}")
        if cls.STORAGE_BACKEND not in ("local", "s3"):
            errors.append(f"STORAGE_BACKEND must be 'local' or 's3', got {cls.STORAGE_BACKEND!r}")
        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
