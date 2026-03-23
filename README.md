# Image Saver Service

A lightweight, secure, containerized image upload API written in Python (FastAPI). Accepts JPEG/PNG images via a REST API and persists them to local disk or S3-compatible object storage (including DigitalOcean Spaces).

## Features

- **Token authentication** — upload tokens managed via a file; hot-reload without restart
- **Content validation** — real MIME type detection via `python-magic` (rejects renamed files)
- **Dual storage backends** — local filesystem or S3/Spaces (`STORAGE_BACKEND=local|s3`)
- **Kubernetes-ready** — HPA, PDB, read-only filesystem, token reload via Secret volume
- **Rate limiting** — per-token isolated buckets via `slowapi`
- **Security** — path traversal protection, file size cap, atomic writes, startup validation

## Quick Start (Docker Compose)

```bash
# 1. Create required directories
mkdir -p storage/images logs config

# 2. Add at least one upload token
echo "YOUR-CLIENT-TOKEN" > config/tokens.txt

# 3. Configure secrets
cp .env.example .env
# Edit .env and set MASTER_TOKEN to a strong random value (≥16 chars)

# 4. Start
docker compose up -d --build
```

## API Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/upload` | `POST` | Upload and save an image | Client token (`tokens.txt`) |
| `/admin/reload-tokens` | `POST` | Reload token list from file | `MASTER_TOKEN` |
| `/health` | `GET` | Liveness/readiness check | None |

### Upload an image

```bash
curl -X POST http://localhost:8080/upload \
  -H "Authorization: Bearer YOUR-CLIENT-TOKEN" \
  -F "image=@./photo.jpg" \
  -F "save_path=users/profile.jpg"
```

**Response:**
```json
{ "message": "Image saved successfully.", "path": "users/profile.jpg" }
```

### Reload tokens

```bash
curl -X POST http://localhost:8080/admin/reload-tokens \
  -H "Authorization: Bearer YOUR-MASTER-TOKEN"
```

**Response:**
```json
{ "message": "Tokens reloaded.", "total_tokens": 3 }
```

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` for local use.

| Variable | Default | Description |
|----------|---------|-------------|
| `MASTER_TOKEN` | *(required)* | Admin token for `/admin/reload-tokens`. Must be ≥16 chars. |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `UPLOAD_FOLDER` | `/app/uploads` | Upload directory (local backend) |
| `TOKEN_FILE_PATH` | `/app/config/tokens.txt` | Path to upload tokens file |
| `TOKEN_RELOAD_INTERVAL` | `10` | Seconds between token file mtime checks |
| `MAX_FILE_SIZE` | `10485760` | Max upload size in bytes (default 10 MB) |
| `ALLOWED_MIME_TYPES` | `image/jpeg,image/png` | Comma-separated allowed MIME types |
| `RATE_LIMIT` | `60/minute` | Per-token rate limit (slowapi format) |
| `TRUSTED_PROXIES` | *(empty)* | CIDRs to trust `X-Forwarded-For` from (e.g. `10.0.0.0/8`) |
| `S3_BUCKET` | *(empty)* | S3 bucket name |
| `S3_ENDPOINT_URL` | *(empty)* | S3 endpoint (e.g. `https://nyc3.digitaloceanspaces.com`) |
| `S3_ACCESS_KEY` | *(empty)* | S3 access key |
| `S3_SECRET_KEY` | *(empty)* | S3 secret key |
| `S3_REGION` | `us-east-1` | S3 region |
| `S3_PUBLIC_URL` | *(empty)* | Optional CDN base URL for returned paths |
| `LOG_FOLDER` | `/app/logs` | Log directory (empty = stdout only, recommended for K8s) |
| `WEB_CONCURRENCY` | `4` | Gunicorn worker count |

## Token file format

One token per line. Lines starting with `#` are ignored.

```
# Upload tokens
CLIENT-A-TOKEN-abc123
CLIENT-B-TOKEN-xyz789
```

## Kubernetes Deployment

Manifests are in `k8s/`. Before deploying:

1. Copy `k8s/secret.example.yaml` → `k8s/secret.yaml`, fill in all values
2. Set your domain and TLS secret name in `k8s/ingress.yaml`
3. Set your container image in `k8s/deployment.yaml`
4. Set `TRUSTED_PROXIES` in `k8s/configmap.yaml` to your ingress controller CIDR

```bash
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml \
              -f k8s/ingress.yaml -f k8s/hpa.yaml -f k8s/pdb.yaml
```

The deployment scales from 2 to 10 replicas based on CPU/memory. Token file updates propagate automatically via Secret volume mounts within ~60s.

## Security Notes

- `MASTER_TOKEN` must never appear in `tokens.txt` — it is a separate credential
- Never commit `.env` or `k8s/secret.yaml` to version control
- For K8s, enable etcd encryption at rest to protect Secret values
