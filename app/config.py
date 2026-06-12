from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str = ""
    chroma_path: str = "./chroma_db"
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 5
    max_retries: int = 3
    llm_model: str = "llama-3.3-70b-versatile"
    embed_model: str = "all-MiniLM-L6-v2"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
