import os, threading

os.environ["STREAMLIT_SERVER_PORT"] = os.getenv("STREAMLIT_SERVER_PORT", "7860")

def run_backend():
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")

t = threading.Thread(target=run_backend, daemon=True)
t.start()

import ui.streamlit_app
