# OPTION 1: Local + ngrok (recommended for prototype demo)
# =========================================================
# Your data stays on your machine. Colleagues get a public URL.
# Setup time: ~5 minutes.

## Step 1: Install ngrok
# Download from https://ngrok.com/download (free account, no credit card)
# Or on Windows with winget:
#   winget install ngrok

## Step 2: Authenticate (one-time)
#   ngrok config add-authtoken YOUR_TOKEN_FROM_NGROK_DASHBOARD

## Step 3: Start dashboard (docker-compose or dev server)
#   docker compose -f docker/docker-compose.yml --env-file .env up -d

## Step 4: Tunnel port 80 to public URL
#   ngrok http 80

# ngrok prints something like:
#   Forwarding  https://abc123.ngrok-free.app -> http://localhost:80
# Share that URL with colleagues. It works as long as your machine is on.

## Step 5 (optional): Fixed subdomain (free tier gives random URLs)
# Free tier: random URL that changes on each ngrok restart
# To get a stable URL: use ngrok free static domain
#   ngrok http --domain=your-chosen-name.ngrok-free.app 80
# (ngrok gives 1 free static domain per account)

## Windows PowerShell one-liner to start everything:
#   docker compose -f docker\docker-compose.yml --env-file .env up -d; ngrok http 80
