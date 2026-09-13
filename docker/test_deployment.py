#!/usr/bin/env python3
"""
Kenya MAM Dashboard -- Docker deployment test script
Run after: docker compose -f docker/docker-compose.yml --env-file .env up -d --build
Usage:      python docker/test_deployment.py [--host localhost] [--port 80]
"""
import sys, time, argparse
try:
    import urllib.request, urllib.error, json
except ImportError:
    print("ERROR: requires Python 3.6+"); sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument('--host', default='localhost')
parser.add_argument('--port', default='80', type=int)
parser.add_argument('--api-port', default='8765', type=int)
args = parser.parse_args()

BASE    = f"http://{args.host}:{args.port}"
API     = f"http://{args.host}:{args.api_port}"
TIMEOUT = 10
PASS, FAIL, WARN = [], [], []

def get(url, label, expect_key=None, via='frontend'):
    target = BASE + url if via == 'frontend' else API + url
    try:
        with urllib.request.urlopen(target, timeout=TIMEOUT) as r:
            body = r.read()
            if expect_key:
                data = json.loads(body)
                if expect_key not in str(data):
                    FAIL.append(f"{label}: missing key '{expect_key}'")
                    print(f"  FAIL  {label}")
                    return None
            PASS.append(label)
            print(f"  OK    {label}  ({len(body)} bytes)")
            return json.loads(body) if body.startswith(b'{') or body.startswith(b'[') else body
    except urllib.error.HTTPError as e:
        FAIL.append(f"{label}: HTTP {e.code}")
        print(f"  FAIL  {label}: HTTP {e.code}")
    except Exception as e:
        FAIL.append(f"{label}: {e}")
        print(f"  FAIL  {label}: {e}")
    return None

print("=" * 60)
print("  Kenya MAM Dashboard -- Deployment Test")
print(f"  Frontend: {BASE}")
print(f"  Backend:  {API}")
print("=" * 60)

print("\n1. Frontend (nginx)")
get('/',         'Serve index.html')
get('/index.html','index.html explicit')

print("\n2. Backend health (direct)")
health = get('/health', 'Health endpoint', via='backend')
if health and isinstance(health, dict):
    status = health.get('status','?')
    n_models = health.get('models_loaded', 0)
    if status == 'ok' and n_models > 0:
        print(f"       {n_models} models loaded")
    elif status != 'ok':
        WARN.append(f"Backend status: {status}")

print("\n3. API via nginx proxy (/api/*)")
get('/api/health',  'API health via proxy', 'status')
models = get('/api/models', 'Models list', 'models')
if models and isinstance(models, dict) and 'models' in models:
    names = list(models['models'].keys())
    print(f"       Models: {names}")
    if len(names) == 0:
        WARN.append("No models loaded -- check DATA_DIR path and contents")

print("\n4. Grid API")
get('/api/grid?variable=onset&layer=median', 'Grid: onset/median')
get('/api/grid?variable=onset&layer=anomaly','Grid: onset/anomaly')

print("\n5. Pixel API")
get('/api/pixel?lat=-1.0&lon=37.0',          'Pixel stats')
get('/api/chirps_historical?lat=-1.0&lon=37.0','CHIRPS historical')

print("\n6. Validation API")
get('/api/validation', 'Validation data')

print()
print("=" * 60)
print(f"  PASSED: {len(PASS)}   FAILED: {len(FAIL)}   WARNINGS: {len(WARN)}")
if FAIL:
    print("\nFailed:")
    for f in FAIL: print(f"  - {f}")
if WARN:
    print("\nWarnings:")
    for w in WARN: print(f"  - {w}")
if not FAIL:
    print("\n  Dashboard is running correctly!")
print("=" * 60)
sys.exit(len(FAIL))
