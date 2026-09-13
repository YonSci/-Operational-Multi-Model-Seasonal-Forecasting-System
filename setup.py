#!/usr/bin/env python3
"""
Kenya MAM v3.0.0 Dashboard - One-Shot Setup Script
====================================================
Run this from the onset-kenya project root:

    python setup.py

What it does:
  1. Creates all required folders
  2. Writes all config files (vite, tailwind, postcss, eslint, index.html)
  3. Copies source files from outputs/ into correct locations
  4. Installs Python backend dependencies
  5. Installs Node frontend dependencies
  6. Validates the setup

Prerequisites:
  - Python 3.9+
  - Node.js 18+ and npm
  - pip

Usage:
  python setup.py              # full setup
  python setup.py --no-install # skip npm/pip installs (structure only)
  python setup.py --check      # verify existing setup without changes
"""

import os
import sys
import json
import shutil
import subprocess
import argparse
from pathlib import Path

# ── Args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--no-install", action="store_true", help="Skip npm and pip installs")
parser.add_argument("--check",      action="store_true", help="Verify setup, no changes")
args = parser.parse_args()

ROOT = Path(__file__).parent.resolve()
OK   = "\033[92m OK \033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"

def log(icon, msg): print(f"  [{icon}] {msg}")
def ok(msg):   log(OK, msg)
def fail(msg): log(FAIL, msg)
def info(msg): log(INFO, msg)

errors = []
def check(cond, msg):
    if cond: ok(msg)
    else:    fail(msg); errors.append(msg)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — CREATE FOLDER STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  STEP 1 — Create folder structure")
print("="*60)

folders = [
    "frontend/src/api",
    "frontend/src/store",
    "frontend/src/components",
    "frontend/public",
    "backend/kenya_api",
    "docker",
    ".claude",
]

for folder in folders:
    path = ROOT / folder
    if not args.check:
        path.mkdir(parents=True, exist_ok=True)
    check(path.exists(), f"Folder: {folder}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — WRITE CONFIGURATION FILES
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  STEP 2 — Write configuration files")
print("="*60)

config_files = {}

# ── vite.config.js ────────────────────────────────────────────────────────────
config_files["frontend/vite.config.js"] = """\
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          mapbox:   ['mapbox-gl'],
          recharts: ['recharts'],
          react:    ['react', 'react-dom'],
        },
      },
    },
  },
})
"""

# ── tailwind.config.js ────────────────────────────────────────────────────────
config_files["frontend/tailwind.config.js"] = """\
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
"""

# ── postcss.config.js ─────────────────────────────────────────────────────────
config_files["frontend/postcss.config.js"] = """\
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
"""

# ── .eslintrc.cjs ─────────────────────────────────────────────────────────────
config_files["frontend/.eslintrc.cjs"] = """\
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  settings: { react: { version: '18.2' } },
  rules: {
    'react/prop-types': 'off',
  },
}
"""

# ── frontend/index.html ───────────────────────────────────────────────────────
config_files["frontend/index.html"] = """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Kenya MAM Forecast Dashboard — ILRI v3.0.0</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body, #root { width: 100%; height: 100%; overflow: hidden; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""

# ── backend/requirements.txt ──────────────────────────────────────────────────
config_files["backend/requirements.txt"] = """\
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
xarray>=2024.2.0
netCDF4>=1.6.5
numpy>=1.26.0
scipy>=1.12.0
h5py>=3.10.0
python-multipart>=0.0.9
"""

# ── backend/kenya_api/__init__.py ─────────────────────────────────────────────
config_files["backend/kenya_api/__init__.py"] = """\
# Kenya MAM Dashboard API routers
"""

# ── .gitignore ────────────────────────────────────────────────────────────────
config_files[".gitignore"] = """\
# Dependencies
frontend/node_modules/
frontend/dist/

# Environment files
.env
frontend/.env
backend/.env

# Python
__pycache__/
*.pyc
*.pyo
.venv/
*.egg-info/

# Data (large NetCDF files)
outputs_*/
CHIRPS/
*.nc

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/settings.json
.idea/

# Docker build artifacts
docker/.env
"""

# ── docker/.dockerignore ──────────────────────────────────────────────────────
config_files["docker/.dockerignore"] = """\
**/__pycache__
**/*.pyc
**/*.pyo
frontend/node_modules
frontend/dist
**/.git
**/.DS_Store
*.md
*.txt
!backend/requirements.txt
"""

# ── vercel.json ───────────────────────────────────────────────────────────────
config_files["vercel.json"] = """\
{
  "rewrites": [
    { "source": "/api/(.*)", "destination": "https://YOUR_NGROK_URL/$1" },
    { "source": "/(.*)",     "destination": "/index.html" }
  ],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=0, must-revalidate" }
      ]
    }
  ]
}
"""

# ── .env (template) ───────────────────────────────────────────────────────────
config_files[".env.example"] = """\
# Copy to .env and fill in your values

# REQUIRED: Absolute path to pipeline output directory (forward slashes on Windows)
# Example: C:/Users/yonas/Documents/ILRI/onset-kenya
DATA_DIR=/path/to/your/pipeline/outputs

# Forecast operational year
OP_YEAR=2026

# Set to 0 to skip bc_daily loading (saves ~4GB RAM, disables A(D) plume)
# LOAD_BC_DAILY=1
"""

# ── frontend/.env.example ─────────────────────────────────────────────────────
config_files["frontend/.env.example"] = """\
# Frontend environment — copy to frontend/.env

# REQUIRED: Mapbox public token from account.mapbox.com
VITE_MAPBOX_TOKEN=pk.eyJ1IjoiWU9VUl9VU0VSTkFNRSIsImEiOi...

# OPTIONAL: Override API base URL (for Vercel + ngrok deploy)
# VITE_API_BASE=https://your-backend.ngrok-free.app
"""

# ── .claude/settings.json ─────────────────────────────────────────────────────
config_files[".claude/settings.json"] = json.dumps({
    "permissions": {
        "allow": [
            "Bash(npm install*)", "Bash(npm run*)", "Bash(npm ci*)",
            "Bash(pip install*)", "Bash(uvicorn*)",
            "Bash(python*)", "Bash(python3*)",
            "Bash(docker*)", "Bash(mkdir*)", "Bash(cp*)",
            "Bash(mv*)", "Bash(cat*)", "Bash(find*)",
            "Bash(ls*)", "Bash(grep*)", "Bash(sed*)",
            "Bash(echo*)", "Bash(node*)", "Bash(npx*)"
        ],
        "deny": ["Bash(rm -rf /)", "Bash(sudo rm*)"]
    },
    "env": {"PYTHONUNBUFFERED": "1"}
}, indent=2)

# Write all config files
for rel_path, content in config_files.items():
    path = ROOT / rel_path
    if not args.check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    check(path.exists(), f"Config: {rel_path}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — COPY SOURCE FILES
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  STEP 3 — Copy source files")
print("="*60)

# Expected source files — adjust output_dir if needed
OUTPUT_DIR = ROOT  # files are generated in-place for this project

# Map: destination path → description
source_files = {
    # Frontend
    "frontend/src/App.jsx":                     "Main React app (all tab components)",
    "frontend/src/main.jsx":                    "React entry point",
    "frontend/src/index.css":                   "CSS variables (dark + light mode)",
    "frontend/src/api/queries.js":              "TanStack Query hooks",
    "frontend/src/store/useDashboardStore.js":  "Zustand store",
    "frontend/src/components/MapPanel.jsx":     "Map panel (5 layer systems)",
    # Backend
    "backend/main.py":                          "FastAPI app",
    "backend/mam_loader.py":                    "Data loader (16 grid layers)",
    "backend/kenya_api/grid.py":               "GET /grid endpoint",
    "backend/kenya_api/pixel.py":              "GET /pixel /chirps_historical /validation",
    "backend/kenya_api/models.py":             "GET /models",
    "backend/kenya_api/sites.py":              "GET /sites",
    "backend/kenya_api/bulletin.py":           "GET /bulletin",
    # Docker
    "docker/Dockerfile.backend":               "Backend Docker image",
    "docker/Dockerfile.frontend":              "Frontend nginx Docker image",
    "docker/Dockerfile.huggingface":           "HuggingFace Spaces single-container",
    "docker/docker-compose.yml":               "Docker Compose (backend + frontend)",
    "docker/nginx.conf":                       "nginx reverse proxy config",
    "docker/requirements.txt":                 "Python deps for Docker build",
    "docker/.env.example":                     "Docker environment template",
    "docker/deploy.sh":                        "Linux/Mac deploy helper",
    "docker/test_deployment.py":               "Automated deployment test",
    "docker/DEPLOYMENT_GUIDE.md":             "Full deploy guide (ngrok/HF/Vercel)",
    "docker/README_DOCKER.md":                "Quick start README",
    # Root
    "skill_weighted_ensemble.py":              "Stage 8 skill-weighting notebook cells",
    "CLAUDE.md":                               "Claude Code project config",
}

for rel_path, description in source_files.items():
    path = ROOT / rel_path
    check(path.exists(), f"Source file ({description[:45]}): {rel_path}")
    if not path.exists():
        info(f"  Missing: place {rel_path} from the delivered files")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — INSTALL DEPENDENCIES
# ══════════════════════════════════════════════════════════════════════════════
if not args.check and not args.no_install:
    print("\n" + "="*60)
    print("  STEP 4 — Install dependencies")
    print("="*60)

    # Python backend
    info("Installing Python backend dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"],
        cwd=ROOT, capture_output=True, text=True
    )
    check(result.returncode == 0, "pip install -r backend/requirements.txt")
    if result.returncode != 0:
        print(result.stderr[-500:])

    # Node frontend
    info("Installing Node frontend dependencies (npm install)...")
    result = subprocess.run(
        ["npm", "install"],
        cwd=ROOT / "frontend", capture_output=True, text=True
    )
    check(result.returncode == 0, "npm install (frontend)")
    if result.returncode != 0:
        print(result.stderr[-500:])
    else:
        # Verify mapbox-gl installed
        mgpath = ROOT / "frontend" / "node_modules" / "mapbox-gl"
        check(mgpath.exists(), "mapbox-gl installed")

elif args.no_install:
    print("\n  [SKIP] Dependency installation (--no-install)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — VALIDATE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  STEP 5 — Validation")
print("="*60)

# Check for non-ASCII in JSX files
jsx_files = list((ROOT / "frontend/src").rglob("*.jsx")) + \
            list((ROOT / "frontend/src").rglob("*.js"))
ascii_clean = True
for jf in jsx_files:
    try:
        raw = jf.read_bytes()
        bad_lines = [i+1 for i, l in enumerate(raw.split(b"\n")) if any(b > 127 for b in l)]
        if bad_lines:
            fail(f"Non-ASCII in {jf.name} at lines: {bad_lines[:5]}")
            ascii_clean = False
    except Exception:
        pass
if ascii_clean:
    ok("All JSX/JS files are ASCII-clean (OXC compatible)")

# Check backend syntax
py_files = list((ROOT / "backend").rglob("*.py"))
import py_compile, io
all_valid = True
for pf in py_files:
    try:
        py_compile.compile(str(pf), doraise=True)
    except py_compile.PyCompileError as e:
        fail(f"Syntax error in {pf.name}: {e}")
        all_valid = False
if all_valid:
    ok(f"All {len(py_files)} Python files pass syntax check")

# Check .env.example exists
check((ROOT / ".env.example").exists(), ".env.example present")
check((ROOT / "frontend/.env.example").exists(), "frontend/.env.example present")


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  SUMMARY")
print("="*60)

if errors:
    print(f"\n  {len(errors)} issue(s) found:")
    for e in errors:
        print(f"    - {e}")
    print()
    print("  Fix the issues above, then re-run: python setup.py")
else:
    print("""
  All checks passed!

  Next steps:
  -----------
  1. Copy frontend/.env.example to frontend/.env
     Add your VITE_MAPBOX_TOKEN from account.mapbox.com

  2. Copy .env.example to .env
     Set DATA_DIR to your pipeline output directory

  3. Start the backend:
     cd backend && uvicorn main:app --reload --port 8765

  4. Start the frontend (new terminal):
     cd frontend && npm run dev

  5. Open browser: http://localhost:5173

  For Docker deployment:
     cp .env.example .env  (fill in DATA_DIR)
     docker compose -f docker/docker-compose.yml --env-file .env up -d --build
     python docker/test_deployment.py
""")

sys.exit(1 if errors else 0)
