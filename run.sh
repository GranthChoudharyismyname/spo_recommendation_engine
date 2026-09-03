#!/usr/bin/env bash
# Start ResuMetr for a live run: the scoring API, then the dashboard.
#
#   ./run.sh
#
# Requires GEMINI_API_KEY in backend/.env. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f backend/.env ]; then
  echo "backend/.env is missing. Copy backend/.env.example and set GEMINI_API_KEY." >&2
  exit 1
fi
if ! grep -q '^GEMINI_API_KEY=.\+' backend/.env; then
  echo "GEMINI_API_KEY is empty in backend/.env. Evaluations cannot run without it." >&2
  exit 1
fi

# Live mode: the dashboard calls the real API rather than the bundled fixture.
printf 'VITE_USE_MOCK=false\n' > frontend/.env.local

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "starting scoring API on :8000"
( set -a; . backend/.env; set +a
  cd backend && .venv/bin/python run_api.py ) &

until curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; do sleep 1; done
echo "API ready"

echo "starting dashboard on :5173"
( cd frontend && npm run dev ) &

echo
echo "  ResuMetr is running:  http://localhost:5173"
echo "  A full evaluation takes 60-180s and makes six model calls."
echo
wait
