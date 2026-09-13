# Kenya MAM Dashboard — Prototype Deployment Guide
# =================================================
# Three free options, detailed step-by-step instructions.
# Written for Windows (your development machine).
#
# Prerequisites (all free, already done):
#   - Docker Desktop installed and running
#   - Project at C:\Users\yonas\Documents\ILRI\onset-kenya\
#   - Pipeline data in your outputs folders
#   - MapLibre migration done (no Mapbox token needed)
# ============================================================


# ============================================================
# OPTION A — LOCAL MACHINE + NGROK TUNNEL
# "Show colleagues a live demo from your laptop"
# ============================================================
#
# How it works:
#   Your laptop runs the dashboard via Docker.
#   ngrok creates a secure tunnel so anyone with the URL
#   can access it over the internet, even through firewalls.
#   Your NetCDF data never leaves your machine.
#
# Pros: Fastest setup, no data upload, full RAM available
# Cons: Laptop must stay on and connected during demo
#       Free tier URL changes on every ngrok restart
#       (fix: claim your 1 free static domain)
# ============================================================

## STEP A-1: Install ngrok
# Go to https://ngrok.com → Sign Up (free, no credit card)
# After signing in, go to: https://dashboard.ngrok.com/get-started/setup
# Download Windows installer and run it, OR use winget:

winget install ngrok

## STEP A-2: Connect your ngrok account (one-time)
# Copy your authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken
# Then run:

ngrok config add-authtoken YOUR_AUTHTOKEN_HERE

## STEP A-3: Claim your free static domain (one-time, optional but recommended)
# Go to: https://dashboard.ngrok.com/domains
# Click "New Domain" — ngrok gives you 1 free static domain
# Example: kenya-mam-ilri.ngrok-free.app
# This URL never changes — you can share it in emails, slides etc.

## STEP A-4: Set up your .env file
# In your project root (C:\Users\yonas\Documents\ILRI\onset-kenya\):

# Create a file named .env with this content:
# (Replace the path with your actual data directory)

DATA_DIR=C:/Users/yonas/Documents/ILRI/onset-kenya
OP_YEAR=2026

# IMPORTANT — Windows paths in Docker must use forward slashes
# e.g.  C:/Users/yonas/Documents/ILRI/onset-kenya  NOT  C:\\Users\\...

## STEP A-5: Build and start the dashboard

cd C:\Users\yonas\Documents\ILRI\onset-kenya

# Build containers (first time takes 3-5 minutes)
docker compose -f docker\docker-compose.yml --env-file .env up -d --build

# Watch backend load data (takes 60-90 seconds)
docker logs mam_backend -f
# Wait until you see: "API ready  →  http://localhost:8080/docs"
# Then press Ctrl+C to stop watching logs

## STEP A-6: Start the ngrok tunnel

# Option A-6a: Random URL (simplest)
ngrok http 80

# Option A-6b: Your static domain (recommended)
ngrok http --domain=kenya-mam-ilri.ngrok-free.app 80

# ngrok will print something like:
#
#   Session Status   online
#   Account          Yonas Mersha (Plan: Free)
#   Forwarding       https://kenya-mam-ilri.ngrok-free.app -> http://localhost:80
#
# Share the Forwarding URL with colleagues.
# The dashboard is now live as long as this window is open.

## STEP A-7: Test it works
python docker/test_deployment.py --host kenya-mam-ilri.ngrok-free.app --port 443

## STEP A-8: When demo is done
# Stop ngrok: Ctrl+C in the ngrok window
# Stop Docker:
docker compose -f docker\docker-compose.yml down

## STEP A-9: Restart for next demo
docker compose -f docker\docker-compose.yml --env-file .env up -d
ngrok http --domain=kenya-mam-ilri.ngrok-free.app 80

## TROUBLESHOOTING
# Dashboard loads but map is blank  → CARTO tiles need internet access
# "502 Bad Gateway"                 → Backend still loading, wait 90s
# ngrok "ERR_NGROK_108"            → Too many connections, wait 1 min
# Docker "port already in use"     → docker compose down then up again
# Windows path error               → Use forward slashes in DATA_DIR




# ============================================================
# OPTION B — HUGGING FACE SPACES (permanent free cloud URL)
# "Always-on public demo, no laptop needed"
# ============================================================
#
# How it works:
#   Hugging Face Spaces is a free ML demo hosting platform.
#   You get a Docker-based Space with 16 GB RAM — enough for
#   your NetCDF data. Your dashboard runs 24/7 at a permanent URL.
#
# Pros: Always on, permanent URL, no laptop required
# Cons: NetCDF files must be uploaded (large files use Git LFS)
#       Cold start takes ~2 minutes after inactivity
#       Free tier CPU is slower than your laptop
# ============================================================

## STEP B-1: Create a Hugging Face account
# Go to https://huggingface.co → Sign Up (free)
# Confirm your email

## STEP B-2: Create a new Space
# Go to: https://huggingface.co/new-space
# Fill in:
#   Owner       : your-username
#   Space name  : kenya-mam-dashboard
#   License     : MIT (or choose)
#   SDK         : Docker          ← IMPORTANT: select Docker
#   Hardware    : CPU Basic (free, 16GB RAM)
# Click "Create Space"
# Your Space URL will be: https://huggingface.co/spaces/your-username/kenya-mam-dashboard

## STEP B-3: Install Git and Git LFS on your machine
# Git:     https://git-scm.com/download/win
# Git LFS: https://git-lfs.com  (needed for large NetCDF files)

# After installing, run once:
git lfs install

## STEP B-4: Clone your Space repository

git clone https://huggingface.co/spaces/your-username/kenya-mam-dashboard
cd kenya-mam-dashboard

## STEP B-5: Copy your project files into the cloned folder

# Copy these from your onset-kenya project:
xcopy /E /I C:\Users\yonas\Documents\ILRI\onset-kenya\backend backend
xcopy /E /I C:\Users\yonas\Documents\ILRI\onset-kenya\frontend frontend
copy  C:\Users\yonas\Documents\ILRI\onset-kenya\docker\Dockerfile.huggingface Dockerfile

# Create a .gitattributes file to track NetCDF files with Git LFS:
echo *.nc filter=lfs diff=lfs merge=lfs -text > .gitattributes
echo *.tif filter=lfs diff=lfs merge=lfs -text >> .gitattributes

## STEP B-6: Copy your data files
# This is the big step — copy all your model output NetCDF files.
# They will be uploaded via Git LFS (compressed).

# Example structure inside the Space repo:
# data/
#   outputs_ECMWF_SEAS5_v3/    <- copy each model folder here
#   outputs_UKMO_GloSea6_v3/
#   ... (all 8 models)
#   CHIRPS/

mkdir data
xcopy /E /I C:\Users\yonas\Documents\ILRI\onset-kenya\outputs_ECMWF_SEAS5_v3 data\outputs_ECMWF_SEAS5_v3
# Repeat for each model folder and CHIRPS

## STEP B-7: Update BASE_DIR in the Dockerfile
# Open Dockerfile.huggingface (now renamed Dockerfile) and verify:
#   ENV BASE_DIR=/data
# This matches where you put the data in Step B-6.

## STEP B-8: Commit and push (this uploads everything)

git add .
git commit -m "Initial Kenya MAM dashboard deployment"
git push

# Git LFS will upload your NetCDF files automatically.
# Progress is shown in the terminal.
# Upload time depends on file sizes — plan for 30-60 min for large datasets.

## STEP B-9: Watch the build
# Go to: https://huggingface.co/spaces/your-username/kenya-mam-dashboard
# Click the "Logs" tab to watch the Docker build and data loading.
# When you see "API ready", the dashboard is live.
# Your permanent URL: https://your-username-kenya-mam-dashboard.hf.space

## STEP B-10: Update the dashboard (when you have new forecast data)
# Replace the data files, commit and push again:
git add data/
git commit -m "Updated MAM 2027 forecast data"
git push
# Space rebuilds automatically.

## TROUBLESHOOTING
# "Out of memory"                → Free tier has 16GB, should be enough
#                                  Try reducing models in mam_loader.py
# Build fails on npm install     → Check Node version in Dockerfile
# Data not loading               → Check BASE_DIR path matches your data/ folder
# HF Space stuck "Building"      → Check Logs tab for error messages




# ============================================================
# OPTION C — VERCEL FRONTEND + NGROK BACKEND (split deploy)
# "Professional permanent URL, backend runs on your laptop"
# ============================================================
#
# How it works:
#   - React frontend is deployed to Vercel (permanent pretty URL)
#   - FastAPI backend runs on your laptop via Docker
#   - ngrok tunnels your backend to the internet
#   - Vercel proxies /api/* calls to your ngrok URL
#
# Pros: Permanent professional URL (kenya-mam.vercel.app)
#       Frontend loads instantly from Vercel CDN
#       Only need laptop on during demo sessions
# Cons: Must update Vercel when ngrok URL changes
#       (fix: use ngrok static domain so URL never changes)
# ============================================================

## STEP C-1: Build the frontend for production

cd C:\Users\yonas\Documents\ILRI\onset-kenya\frontend
npm run build
# This creates frontend/dist/ with your built React app

## STEP C-2: Sign up for Vercel (free)
# Go to https://vercel.com → Sign Up with GitHub (free)
# No credit card needed

## STEP C-3: Install Vercel CLI

npm install -g vercel

## STEP C-4: Set your ngrok static domain in vercel.json
# First follow OPTION A Steps A-1 and A-2 to get ngrok installed and your static domain.
# Then edit vercel.json (in your project root):
#
# Replace "YOUR_NGROK_URL" with your actual ngrok static domain:
#   https://kenya-mam-ilri.ngrok-free.app
#
# The file should look like:
# {
#   "rewrites": [
#     { "source": "/api/(.*)", "destination": "https://kenya-mam-ilri.ngrok-free.app/$1" },
#     { "source": "/(.*)",     "destination": "/index.html" }
#   ]
# }

## STEP C-5: Deploy frontend to Vercel

cd C:\Users\yonas\Documents\ILRI\onset-kenya
vercel deploy --prod

# Vercel CLI will ask a few questions (first time):
#   Set up and deploy? Y
#   Which scope? (your account)
#   Link to existing project? N
#   Project name? kenya-mam-dashboard
#   Which directory is your code? ./frontend
# Then it deploys and gives you a URL like:
#   https://kenya-mam-dashboard.vercel.app

## STEP C-6: For every demo session, start your backend + ngrok

# Start Docker backend
docker compose -f docker\docker-compose.yml --env-file .env up -d

# Wait for data load
docker logs mam_backend -f
# Ctrl+C when you see "API ready"

# Start ngrok with your static domain
ngrok http --domain=kenya-mam-ilri.ngrok-free.app 80

# Your dashboard is now live at:
#   https://kenya-mam-dashboard.vercel.app
# (Always available — even when backend is off, page loads;
#  but data only works when ngrok+docker are running)

## STEP C-7: Test the full stack
# Open https://kenya-mam-dashboard.vercel.app in browser
# You should see the dashboard loading models

## TROUBLESHOOTING
# "Failed to fetch" on data         → ngrok not running, start it
# Vercel shows CORS error           → Add to FastAPI CORS origins in main.py:
#                                     "https://kenya-mam-dashboard.vercel.app"
# vercel.json rewrite not working   → Re-deploy after editing vercel.json:
#                                     vercel deploy --prod
# API 404 on Vercel                 → Check vercel.json source pattern is "/api/(.*)"




# ============================================================
# COMPARISON SUMMARY
# ============================================================
#
#  Feature                Option A      Option B         Option C
#  ──────────────────     ─────────     ──────────────   ─────────────────
#  Setup time             5 min         2-3 hours        30 min
#  URL type               Random/static Permanent        Permanent
#  Laptop required        Yes           No               Yes (for demo)
#  Data upload            No            Yes (Git LFS)    No
#  Always online          No            Yes              No (frontend only)
#  RAM available          Your laptop   16 GB            Your laptop
#  Best for               Quick demos   Permanent demo   Clean URL + local
#
# RECOMMENDATION:
#   → Start with Option A (5 min, works immediately)
#   → If you need a permanent URL for a presentation: Option C
#   → If you want it always-on without your laptop: Option B
# ============================================================
