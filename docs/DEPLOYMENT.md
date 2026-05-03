# RepoMind — Deployment Guide

> Production deployment guide covering Docker, cloud platforms, and CI/CD configuration.

---

## Table of Contents

1. [Deployment Overview](#1-deployment-overview)
2. [Docker Deployment (Recommended)](#2-docker-deployment-recommended)
3. [Environment Variables for Production](#3-environment-variables-for-production)
4. [Deploy to a Linux VPS (Ubuntu/Debian)](#4-deploy-to-a-linux-vps-ubuntudebian)
5. [Deploy to Railway](#5-deploy-to-railway)
6. [Deploy to Render](#6-deploy-to-render)
7. [Deploy to AWS EC2](#7-deploy-to-aws-ec2)
8. [Fix & Complete the CI/CD Pipeline](#8-fix--complete-the-cicd-pipeline)
9. [Reverse Proxy with Nginx](#9-reverse-proxy-with-nginx)
10. [Health Checks & Monitoring](#10-health-checks--monitoring)
11. [Security Checklist](#11-security-checklist)

---

## 1. Deployment Overview

RepoMind is a stateless FastAPI service. It holds job state in-memory (no external database required), so each instance is self-contained. This makes it easy to deploy but means job state is lost on restart — see Section 10 for notes on persistence if needed.

**Minimum production requirements:**

| Resource | Minimum | Recommended                      |
| -------- | ------- | -------------------------------- |
| RAM      | 512 MB  | 1–2 GB                           |
| CPU      | 1 vCPU  | 2 vCPU                           |
| Disk     | 1 GB    | 5 GB (for repo cloning)          |
| Python   | 3.11    | 3.11                             |
| Port     | 8000    | 8000 (or behind Nginx on 80/443) |

---

## 2. Docker Deployment (Recommended)

Docker is the fastest and most reproducible way to deploy RepoMind. The `Dockerfile` in the repository is production-ready.

### Build the image

```bash
# From the project root
docker build -t repomind:latest .
```

### Run the container

```bash
docker run -d \
  --name repomind \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  repomind:latest
```

| Flag                       | Purpose                                   |
| -------------------------- | ----------------------------------------- |
| `-d`                       | Run in background (detached)              |
| `--name repomind`          | Name the container for easy management    |
| `-p 8000:8000`             | Map host port 8000 to container port 8000 |
| `--env-file .env`          | Load secrets from your `.env` file        |
| `--restart unless-stopped` | Auto-restart on crash or reboot           |

### Verify it's running

```bash
docker ps
curl http://localhost:8000/health
# Expected: {"status": "ok"}
```

### View logs

```bash
docker logs repomind -f
```

### Stop and remove

```bash
docker stop repomind
docker rm repomind
```

### Update to a new version

```bash
git pull
docker build -t repomind:latest .
docker stop repomind && docker rm repomind
docker run -d --name repomind -p 8000:8000 --env-file .env --restart unless-stopped repomind:latest
```

---

## 3. Environment Variables for Production

Never store secrets in your Docker image or source code. Always inject them at runtime via environment variables.

### Required variables

| Variable          | Description                               | Example         |
| ----------------- | ----------------------------------------- | --------------- |
| `OPENAI_API_KEY`  | OpenAI secret key                         | `sk-proj-...`   |
| `GITHUB_TOKEN`    | GitHub PAT with `repo` scope              | `ghp_...`       |
| `GITHUB_USERNAME` | GitHub username associated with the token | `your-username` |

### Optional tuning variables

| Variable         | Default       | Description                            |
| ---------------- | ------------- | -------------------------------------- |
| `LLM_MODEL`      | `gpt-4o`      | LLM model to use                       |
| `MAX_PLAN_STEPS` | `15`          | Max steps the planner produces per job |
| `APP_ENV`        | `development` | Set to `production` in prod            |
| `LOG_LEVEL`      | `INFO`        | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

### Production `.env` example

```env
OPENAI_API_KEY=sk-proj-...
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=repomind-bot
LLM_MODEL=gpt-4o
MAX_PLAN_STEPS=15
APP_ENV=production
LOG_LEVEL=WARNING
```

### Providing secrets without a `.env` file

On cloud platforms that don't support `.env` files, pass each variable individually:

```bash
docker run -d \
  -e OPENAI_API_KEY="sk-proj-..." \
  -e GITHUB_TOKEN="ghp_..." \
  -e GITHUB_USERNAME="repomind-bot" \
  -e APP_ENV="production" \
  -p 8000:8000 \
  repomind:latest
```

---

## 4. Deploy to a Linux VPS (Ubuntu/Debian)

This section covers a bare-metal or VPS deployment without Docker.

### Step 1 — Install Python 3.11

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git
```

### Step 2 — Create a dedicated user

```bash
sudo useradd -m -s /bin/bash repomind
sudo su - repomind
```

### Step 3 — Clone and install

```bash
git clone https://github.com/your-org/repomind.git
cd repomind
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Step 4 — Configure environment

```bash
cp config/.env.example .env
nano .env   # Fill in all required values
```

### Step 5 — Run as a systemd service

Create a service file so RepoMind starts automatically on boot:

```bash
sudo nano /etc/systemd/system/repomind.service
```

Paste the following, replacing `/home/repomind/repomind` with your actual path:

```ini
[Unit]
Description=RepoMind FastAPI Service
After=network.target

[Service]
User=repomind
WorkingDirectory=/home/repomind/repomind
EnvironmentFile=/home/repomind/repomind/.env
ExecStart=/home/repomind/repomind/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable repomind
sudo systemctl start repomind
sudo systemctl status repomind
```

### Step 6 — Firewall

```bash
sudo ufw allow 8000/tcp
sudo ufw enable
```

If using Nginx (recommended), block direct access to port 8000 and only expose 443:

```bash
sudo ufw delete allow 8000/tcp
sudo ufw allow 'Nginx Full'
```

---

## 5. Deploy to Railway

[Railway](https://railway.app) is the fastest zero-config cloud option.

1. Push your code to GitHub.
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
3. Select your `repomind` repository.
4. Railway auto-detects the `Dockerfile` and builds it.
5. Go to your service → **Variables** → add all required env vars:
   - `OPENAI_API_KEY`
   - `GITHUB_TOKEN`
   - `GITHUB_USERNAME`
   - `APP_ENV=production`
6. Railway provides a public HTTPS URL automatically (e.g. `https://repomind-production.up.railway.app`).
7. Verify: `curl https://repomind-production.up.railway.app/health`

---

## 6. Deploy to Render

1. Push your code to GitHub.
2. Go to [render.com](https://render.com) → **New** → **Web Service**.
3. Connect your GitHub repo.
4. Set:
   - **Environment:** Docker
   - **Dockerfile Path:** `./Dockerfile`
   - **Port:** `8000`
5. Under **Environment Variables**, add `OPENAI_API_KEY`, `GITHUB_TOKEN`, `GITHUB_USERNAME`, `APP_ENV=production`.
6. Click **Deploy**.

Render provides a free tier but it spins down idle services after 15 minutes. Use a paid plan for production.

---

## 7. Deploy to AWS EC2

### Launch an instance

1. Go to EC2 → **Launch Instance**.
2. Choose **Ubuntu Server 24.04 LTS** (or 22.04).
3. Instance type: `t3.small` (1 vCPU, 2 GB RAM) or larger.
4. Create or select a key pair for SSH access.
5. In **Security Group**, open inbound ports: `22` (SSH), `443` (HTTPS), `80` (HTTP).
6. Launch.

### Connect and install Docker

```bash
ssh -i your-key.pem ubuntu@<your-ec2-ip>

# Install Docker
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable docker
sudo usermod -aG docker ubuntu
# Log out and back in for group changes to take effect
```

### Deploy

```bash
git clone https://github.com/your-org/repomind.git
cd repomind

# Create .env with your secrets
nano .env

# Build and run
docker build -t repomind:latest .
docker run -d --name repomind -p 8000:8000 --env-file .env --restart unless-stopped repomind:latest
```

### Assign an Elastic IP

In the EC2 console, allocate and associate an Elastic IP to your instance so the IP doesn't change on restart.

---

## 8. Fix & Complete the CI/CD Pipeline

The current `ci.yml` is missing the lint, type-check, and push steps documented in the README. Here is the corrected and complete pipeline.

Replace `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dev dependencies
        run: pip install -e ".[dev]"

      - name: Check formatting with black
        run: black --check .

      - name: Lint with ruff
        run: ruff check .

      - name: Type check with mypy
        run: mypy agent/ api/ tools/ utils/ config/ --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run tests with coverage
        run: pytest tests/ -v --tb=short --cov=. --cov-report=xml

      - name: Upload coverage report
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
        continue-on-error: true

  docker-build:
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Log in to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push Docker image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ${{ secrets.DOCKERHUB_USERNAME }}/repomind:latest
            ${{ secrets.DOCKERHUB_USERNAME }}/repomind:${{ github.sha }}
```

### GitHub Secrets to configure

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret name          | Value                                       |
| -------------------- | ------------------------------------------- |
| `DOCKERHUB_USERNAME` | Your Docker Hub username                    |
| `DOCKERHUB_TOKEN`    | Docker Hub access token (not your password) |

Create a Docker Hub access token at [hub.docker.com/settings/security](https://hub.docker.com/settings/security).

---

## 9. Reverse Proxy with Nginx

Running RepoMind behind Nginx lets you use HTTPS (via Let's Encrypt) and serve on port 443 instead of 8000.

### Install Nginx and Certbot

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

### Create an Nginx site config

```bash
sudo nano /etc/nginx/sites-available/repomind
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # For long-running agent jobs
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/repomind /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Enable HTTPS with Let's Encrypt

```bash
sudo certbot --nginx -d your-domain.com
```

Certbot auto-renews. Verify auto-renewal works:

```bash
sudo certbot renew --dry-run
```

---

## 10. Health Checks & Monitoring

### Built-in health endpoints

| Endpoint  | Method | Expected response                              |
| --------- | ------ | ---------------------------------------------- |
| `/`       | GET    | `{"service": "RepoMind", "status": "running"}` |
| `/health` | GET    | `{"status": "ok"}`                             |

### Docker health check (add to `docker run`)

```bash
docker run -d \
  --name repomind \
  --health-cmd="curl -f http://localhost:8000/health || exit 1" \
  --health-interval=30s \
  --health-timeout=5s \
  --health-retries=3 \
  -p 8000:8000 \
  --env-file .env \
  repomind:latest
```

### View health status

```bash
docker inspect --format='{{.State.Health.Status}}' repomind
```

### Notes on in-memory job state

The current `JobManager` stores jobs in a Python dict in RAM. This means:

- All job records are lost when the server restarts.
- Running multiple container instances will have separate job stores (no shared state).

For production use with multiple instances or persistent job history, replace `utils/job_manager.py` with a Redis-backed store:

```bash
pip install redis
```

Then replace `self._store: dict` with a Redis client using `job_id` as the key and JSON-serialised `JobRecord` as the value.

---

## 11. Security Checklist

Before going live, verify each item:

- [ ] `.env` is **not** committed to Git — check with `git status`
- [ ] `APP_ENV=production` is set
- [ ] `LOG_LEVEL` is `WARNING` or `ERROR` in production (avoids leaking LLM prompts to logs)
- [ ] GitHub PAT has the **minimum required scope** — `repo` only, with an expiration date
- [ ] OpenAI key has **usage limits** set at [platform.openai.com/account/limits](https://platform.openai.com/account/limits)
- [ ] HTTPS is enabled — never run RepoMind over plain HTTP with real secrets
- [ ] Container is **not running as root** (consider adding `USER 1001` to the Dockerfile)
- [ ] Docker Hub token used in CI is a **limited-scope access token**, not your account password
- [ ] Rate limiting is configured on Nginx or at the load balancer level
- [ ] Firewall blocks direct access to port 8000 if Nginx is in front

### Add a non-root user to the Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir fastapi uvicorn pydantic pydantic-settings \
    python-dotenv langchain langchain-openai langchain-community langchain-core \
    gitpython PyGithub httpx pytest pytest-asyncio

# Create and switch to a non-root user
RUN useradd -m appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
