# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Local dev (Docker Compose):**
```bash
docker-compose up -d --build
docker-compose logs -f image-saver
docker-compose down
```

**Test the API:**
```bash
# Upload
curl -X POST http://localhost:8080/upload \
  -H "Authorization: Bearer CLIENTE-A-TOKEN-123" \
  -F "image=@./photo.jpg" \
  -F "save_path=users/profile.jpg"

# Health
curl http://localhost:8080/health

# Reload tokens (master token required)
curl -X POST http://localhost:8080/admin/reload-tokens \
  -H "Authorization: Bearer CHANGE_ME_BEFORE_DEPLOY"
```

**Kubernetes:**
```bash
# First deploy
cp k8s/secret.example.yaml k8s/secret.yaml   # fill in values
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml \
              -f k8s/ingress.yaml -f k8s/hpa.yaml -f k8s/pdb.yaml

# Rolling update after pushing a new image
kubectl rollout restart deployment/image-saver
kubectl rollout status deployment/image-saver
```

## Architecture

Three source files, all application logic:

| File | Purpose |
|------|---------|
| `config.py` | All env var config in one place with defaults |
| `storage.py` | `LocalStorage` and `S3Storage` backends + `sanitize_path()` |
| `app.py` | FastAPI app: auth, rate limiting, upload endpoint, background reload |

### Storage backends (`STORAGE_BACKEND` env var)

- **`local`** — writes to `UPLOAD_FOLDER` on disk (docker-compose default)
- **`s3`** — uploads via `aioboto3` with AES-256 server-side encryption; DigitalOcean Spaces is S3-compatible, set `S3_ENDPOINT_URL=https://<region>.digitaloceanspaces.com`

`sanitize_path()` in `storage.py` sanitizes every path component with `secure_filename`, rejecting `..` and empty segments. `LocalStorage` additionally checks the resolved absolute path stays inside the upload root.

### Token management

`TokenStore` is a thin async wrapper around a `set`. It is populated at startup and by a background `asyncio` task that reloads from `TOKEN_FILE_PATH` every `TOKEN_RELOAD_INTERVAL` seconds (default 30s).

In Kubernetes, tokens live in `Secret/image-saver-tokens` (mounted as `/app/config/tokens.txt`). When the Secret is updated, K8s propagates the change via an atomic symlink swap within ~1 minute. The background watcher checks the file's mtime every `TOKEN_RELOAD_INTERVAL` seconds (default 10s) and reloads only when it changes — all replicas pick it up automatically with no rolling restart needed.

`/admin/reload-tokens` triggers an immediate reload on the pod that receives the request. For full fleet reload, rely on the background watcher or do a rolling restart.

### Concurrency

FastAPI runs on Gunicorn with `UvicornWorker` (ASGI). S3 uploads use `aioboto3` (non-blocking). Local file I/O is offloaded to a thread-pool via `asyncio.run_in_executor`. The default `--workers 4` is suitable for CPU-bound validation; tune with `WEB_CONCURRENCY` env var.

### Kubernetes deployment

```
k8s/
├── configmap.yaml       non-sensitive env vars
├── secret.example.yaml  template — copy to secret.yaml (never commit secret.yaml)
├── deployment.yaml      2 replicas, readOnlyRootFilesystem, liveness/readiness probes
├── service.yaml         ClusterIP on port 80 → 5000
├── ingress.yaml         nginx ingress, TLS via cert-manager, nginx-level rate limiting
├── hpa.yaml             CPU 70% / memory 80% triggers, scale 2–10 replicas
└── pdb.yaml             minAvailable: 1 (safe rolling updates)
```

Two things to set in `k8s/ingress.yaml` before deploying: `host` and the TLS secret name.

The deployment uses `readOnlyRootFilesystem: true` + all capabilities dropped. A `Memory`-backed `emptyDir` is mounted at `/tmp` for runtime temp files. File logging is disabled in K8s (`LOG_FOLDER: ""`); logs go to stdout and are collected by the cluster's log aggregator.
