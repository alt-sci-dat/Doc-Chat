import os
import uuid

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="DocChat",
    page_icon="📄",
    layout="wide",
)

st.markdown("""
<style>
    .main > div { padding-bottom: 2rem; }
    .stApp header { background-color: transparent; }
    .citation-block {
        background: #f0f2f6;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
        border-left: 4px solid #4CAF50;
    }
    .refusal {
        background: #fff3e0;
        border-left: 4px solid #ff9800;
        padding: 12px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


def init_session():
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "indexed_docs" not in st.session_state:
        st.session_state.indexed_docs = []
    if "citations_store" not in st.session_state:
        st.session_state.citations_store = {}


def fetch_health():
    try:
        resp = requests.get(
            f"{API_URL}/health",
            params={"session_id": st.session_state.session_id},
            timeout=5,
        )
        if resp.ok:
            data = resp.json()
            st.session_state.indexed_docs = data.get("docs_ingested", [])
            return data
    except requests.ConnectionError:
        pass
    return None


def upload_pdfs(files):
    files_for_req = [("files", (f.name, f.read(), "application/pdf")) for f in files]
    resp = requests.post(
        f"{API_URL}/upload",
        files=files_for_req,
        params={"session_id": st.session_state.session_id},
        timeout=120,
    )
    if resp.ok:
        data = resp.json()
        st.success(f"✅ Indexed {data['filename']}: {data['pages']} pages, {data['chunks']} chunks in {data['time_taken']}s")
        fetch_health()
    else:
        detail = resp.json().get("detail", "Upload failed")
        st.error(f"❌ {detail}")


def send_message(question):
    resp = requests.post(
        f"{API_URL}/chat",
        json={"question": question, "session_id": st.session_state.session_id},
        timeout=60,
    )
    if resp.ok:
        return resp.json()
    return None


init_session()
fetch_health()


with st.sidebar:
    st.title("📄 DocChat")
    st.caption("Chat with your PDFs")

    st.divider()
    st.subheader("Upload Documents")
    uploaded_files = st.file_uploader(
        "Choose PDF files",
        type="pdf",
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if uploaded_files:
        upload_pdfs(uploaded_files)

    st.divider()
    st.subheader("Indexed Documents")
    if st.session_state.indexed_docs:
        for doc in st.session_state.indexed_docs:
            st.markdown(f"- 📘 {doc}")
    else:
        st.caption("No documents indexed yet.")

    if st.button("🗑️ Clear My Documents", type="secondary", use_container_width=True):
        try:
            requests.post(
                f"{API_URL}/reset",
                params={"session_id": st.session_state.session_id},
                timeout=5,
            )
            st.session_state.indexed_docs = []
            st.session_state.messages = []
            st.session_state.citations_store = {}
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()
        except requests.ConnectionError:
            st.error("Backend not reachable")

    st.divider()
    health_data = fetch_health()
    if health_data:
        st.metric("Chunks Indexed", health_data.get("chunks_indexed", 0))
    else:
        st.warning("⚠️ Backend offline")


st.title("💬 Chat with Your Documents")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        msg_id = id(msg)
        if msg["role"] == "assistant" and msg_id in st.session_state.citations_store:
            citations = st.session_state.citations_store[msg_id]
            if citations:
                with st.expander("📚 Sources"):
                    for c in citations:
                        st.markdown(
                            f'<div class="citation-block">'
                            f'<strong>{c["filename"]}</strong> — Page {c["page"]}<br>'
                            f'<code>{c["chunk_id"]}</code><br>'
                            f'<em>"{c["snippet"][:200]}..."</em>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )


if prompt := st.chat_input("Ask a question about your documents..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching documents..."):
            result = send_message(prompt)

        if result:
            answer = result["answer"]
            citations = result.get("citations", [])

            if "can't find this" in answer.lower():
                st.markdown(f'<div class="refusal">{answer}</div>', unsafe_allow_html=True)
            elif "unavailable" in answer.lower() or "rate limit" in answer.lower():
                st.warning(answer)
            else:
                st.markdown(answer)

            msg_entry = {"role": "assistant", "content": answer}
            st.session_state.messages.append(msg_entry)
            msg_id = id(msg_entry)
            st.session_state.citations_store[msg_id] = citations

            if citations:
                with st.expander("📚 Sources", expanded=True):
                    for c in citations:
                        st.markdown(
                            f'<div class="citation-block">'
                            f'<strong>{c["filename"]}</strong> — Page {c["page"]}<br>'
                            f'<code>{c["chunk_id"]}</code><br>'
                            f'<em>"{c["snippet"][:200]}..."</em>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
        else:
            st.error("Failed to get response from backend")
