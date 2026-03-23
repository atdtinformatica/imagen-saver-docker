import asyncio
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

import magic
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from config import Config
from storage import LocalStorage, S3Storage, StorageBackend, sanitize_path

# ── Logging ────────────────────────────────────────────────────────────────────


class _ClientIPFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "client_ip"):
            record.client_ip = "SERVER"
        return True


_fmt = logging.Formatter("%(asctime)s %(levelname)s IP:%(client_ip)s %(message)s")
_stream_h = logging.StreamHandler()
_stream_h.setFormatter(_fmt)
_stream_h.addFilter(_ClientIPFilter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers = [_stream_h]

if Config.LOG_FOLDER:
    os.makedirs(Config.LOG_FOLDER, exist_ok=True)
    try:
        _file_h = logging.FileHandler(os.path.join(Config.LOG_FOLDER, "server.log"))
        _file_h.setFormatter(_fmt)
        _file_h.addFilter(_ClientIPFilter())
        root_logger.addHandler(_file_h)
    except OSError as exc:
        logging.warning(f"File logging disabled: {exc}")

logger = logging.getLogger(__name__)

# ── Token store ────────────────────────────────────────────────────────────────


class TokenStore:
    def __init__(self) -> None:
        self._tokens: set[str] = set()
        self._lock = asyncio.Lock()

    async def load(self, path: str) -> int:
        """Load tokens from file. Returns count on success, -1 on error."""
        try:
            with open(path) as fh:
                tokens = {
                    line.strip()
                    for line in fh
                    if line.strip() and not line.strip().startswith("#")
                }
            async with self._lock:
                self._tokens = tokens
            return len(tokens)
        except FileNotFoundError:
            logger.critical(f"Token file not found: {path}", extra={"client_ip": "BOOTSTRAP"})
            return -1
        except OSError as exc:
            logger.critical(f"Cannot read token file: {exc}", extra={"client_ip": "BOOTSTRAP"})
            return -1

    def contains(self, token: str) -> bool:
        return token in self._tokens  # GIL-safe for set reads

    @property
    def count(self) -> int:
        return len(self._tokens)


token_store = TokenStore()


async def _watch_token_file() -> None:
    """Background task: reload tokens only when the file actually changes.

    Uses mtime polling instead of unconditional reads. This works correctly
    with Kubernetes Secret volume mounts, which update via an atomic symlink
    swap — the new file gets a fresh mtime, triggering a reload within
    TOKEN_RELOAD_INTERVAL seconds (default 10s).
    """
    last_mtime: float = 0.0
    while True:
        await asyncio.sleep(Config.TOKEN_RELOAD_INTERVAL)
        try:
            mtime = os.path.getmtime(Config.TOKEN_FILE_PATH)
        except OSError:
            continue
        if mtime == last_mtime:
            continue
        last_mtime = mtime
        count = await token_store.load(Config.TOKEN_FILE_PATH)
        if count >= 0:
            logger.info(
                f"Token file changed: {count} tokens reloaded",
                extra={"client_ip": "BACKGROUND"},
            )


# ── Storage backend ────────────────────────────────────────────────────────────


def _build_storage() -> StorageBackend:
    if Config.STORAGE_BACKEND == "s3":
        return S3Storage(
            bucket=Config.S3_BUCKET,
            endpoint_url=Config.S3_ENDPOINT_URL,
            access_key=Config.S3_ACCESS_KEY,
            secret_key=Config.S3_SECRET_KEY,
            region=Config.S3_REGION,
            public_url=Config.S3_PUBLIC_URL,
        )
    return LocalStorage(Config.UPLOAD_FOLDER)


# ── App lifecycle ──────────────────────────────────────────────────────────────


_WEAK_TOKENS = {
    "",
    "CHANGE_ME_BEFORE_DEPLOY",
    "ADMIN_MASTER_TOKEN_DEFAULT_CHANGE_ME",
    "change-me-strong-random-value",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start with a missing or known-weak master token
    if not Config.MASTER_TOKEN or Config.MASTER_TOKEN in _WEAK_TOKENS or len(Config.MASTER_TOKEN) < 16:
        raise RuntimeError(
            "MASTER_TOKEN is not set or is too weak. "
            "Set a strong random value (≥16 chars) in your .env file before starting."
        )

    count = await token_store.load(Config.TOKEN_FILE_PATH)
    logger.info(
        f"Startup: {count} tokens loaded, backend={Config.STORAGE_BACKEND}",
        extra={"client_ip": "STARTUP"},
    )
    reload_task = asyncio.create_task(_watch_token_file())
    yield
    reload_task.cancel()
    try:
        await reload_task
    except asyncio.CancelledError:
        pass


# ── FastAPI app ────────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    lifespan=lifespan,
    # Disable auto-generated docs in production
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

storage: StorageBackend = _build_storage()


def _parse_trusted_proxies(raw: str) -> list:
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(f"Invalid TRUSTED_PROXIES entry ignored: {entry!r}")
    return networks


_trusted_proxies = _parse_trusted_proxies(Config.TRUSTED_PROXIES)


class _ProxyMiddleware(BaseHTTPMiddleware):
    """Populate request.client from X-Forwarded-For only when the request
    arrives from a trusted proxy IP/CIDR (TRUSTED_PROXIES env var).
    If TRUSTED_PROXIES is empty, XFF is ignored and the raw TCP IP is used.
    """

    async def dispatch(self, request: Request, call_next):
        if _trusted_proxies:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                client_ip = (request.scope.get("client") or ("", 0))[0]
                try:
                    addr = ipaddress.ip_address(client_ip)
                    if any(addr in net for net in _trusted_proxies):
                        real_ip = xff.split(",")[0].strip()
                        if real_ip:
                            request.scope["client"] = (real_ip, 0)
                except ValueError:
                    pass  # malformed connecting IP — leave scope unchanged
        return await call_next(request)


app.add_middleware(_ProxyMiddleware)

# ── Auth ───────────────────────────────────────────────────────────────────────


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    if len(parts) == 1:
        return parts[0]
    return None


def require_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    ip = request.client.host if request.client else "unknown"
    token = _extract_token(authorization)
    if not token:
        logger.warning("Auth failed: no token provided", extra={"client_ip": ip})
        raise HTTPException(401, "Authorization header required. Use 'Bearer <token>'.")
    if not token_store.contains(token):
        logger.warning(
            f"Auth failed: invalid token prefix={token[:5]!r}",
            extra={"client_ip": ip},
        )
        raise HTTPException(403, "Invalid or unauthorized token.")
    logger.info(f"Auth OK: token prefix={token[:5]!r}", extra={"client_ip": ip})
    return token


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "tokens": token_store.count, "backend": Config.STORAGE_BACKEND}


@app.post("/admin/reload-tokens")
async def reload_tokens(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
):
    ip = request.client.host if request.client else "unknown"
    log = {"client_ip": ip}
    token = _extract_token(authorization)

    if not Config.MASTER_TOKEN or token != Config.MASTER_TOKEN:
        logger.warning("Unauthorized admin access attempt", extra=log)
        raise HTTPException(403, "Valid master token required.")

    count = await token_store.load(Config.TOKEN_FILE_PATH)
    logger.info(f"Tokens reloaded via admin endpoint: {count} tokens", extra=log)
    return {"message": "Tokens reloaded.", "total_tokens": count}


@app.post("/upload")
@limiter.limit(Config.RATE_LIMIT)
async def upload_image(
    request: Request,
    image: UploadFile,
    save_path: Annotated[str, Form()],
    token: Annotated[str, Depends(require_token)],
):
    ip = request.client.host if request.client else "unknown"
    log = {"client_ip": ip}

    # File size check — stream in chunks so oversized files are rejected
    # immediately without buffering the full body into memory.
    chunks: list[bytes] = []
    size = 0
    async for chunk in image:
        size += len(chunk)
        if size > Config.MAX_FILE_SIZE:
            logger.warning(
                f"Upload rejected: file exceeds {Config.MAX_FILE_SIZE}B", extra=log
            )
            raise HTTPException(
                413, f"File exceeds maximum allowed size of {Config.MAX_FILE_SIZE} bytes."
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    # Content-based MIME type validation
    try:
        real_mime = magic.from_buffer(data[:2048], mime=True)
    except Exception as exc:
        logger.error(f"MIME detection error: {exc}", extra=log)
        raise HTTPException(500, "Internal error while validating file.")

    if real_mime not in Config.ALLOWED_MIME_TYPES:
        logger.warning(f"Upload rejected: MIME={real_mime!r}", extra=log)
        raise HTTPException(
            400,
            f"File type '{real_mime}' is not allowed. "
            f"Allowed types: {', '.join(sorted(Config.ALLOWED_MIME_TYPES))}.",
        )

    # Path sanitization
    key = sanitize_path(save_path)
    if not key:
        logger.warning(f"Upload rejected: invalid save_path={save_path!r}", extra=log)
        raise HTTPException(400, "Invalid save_path.")

    logger.info(
        f"Saving {image.filename!r} → {key!r} ({real_mime})", extra=log
    )

    try:
        result = await storage.save(data, key, real_mime)
    except ValueError as exc:
        logger.error(f"Storage validation error: {exc}", extra=log)
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.error(f"Storage failure: {exc}", extra=log)
        raise HTTPException(500, "Failed to save file.")

    logger.info(f"Upload complete → {result!r}", extra=log)
    return {"message": "Image saved successfully.", "path": result}
