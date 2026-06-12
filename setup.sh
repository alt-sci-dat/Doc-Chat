#!/usr/bin/env bash
set -euo pipefail

echo "🔧 DocChat — Setup"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Created .env from .env.example — add your GROQ_API_KEY"
fi

echo "📦 Installing dependencies..."
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet -r requirements.txt

echo "✅ Done. Run:  source .venv/bin/activate && uvicorn app.main:app --reload"
