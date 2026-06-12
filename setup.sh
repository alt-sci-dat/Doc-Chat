#!/usr/bin/env bash
set -euo pipefail

echo "🔧 DocChat — Setup"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Created .env from .env.example — add your GROQ_API_KEY"
fi

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    echo "🍎 Installing system deps (Tesseract + Poppler) via Homebrew..."
    brew list tesseract 2>/dev/null || brew install tesseract
    brew list poppler 2>/dev/null || brew install poppler
elif [ -f /etc/debian_version ]; then
    echo "🐧 Installing system deps via apt..."
    sudo apt-get update -qq && sudo apt-get install -y -qq tesseract-ocr poppler-utils
fi

echo "📦 Installing dependencies..."
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet -r requirements.txt

echo "✅ Done. Run:  source .venv/bin/activate && uvicorn app.main:app --reload"
