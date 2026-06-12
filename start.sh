#!/bin/bash
set -e

echo "Starting FastAPI backend on :8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "Starting Streamlit UI on :7860..."
streamlit run ui/streamlit_app.py --server.port=7860 --server.address=0.0.0.0 &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

wait $FRONTEND_PID
