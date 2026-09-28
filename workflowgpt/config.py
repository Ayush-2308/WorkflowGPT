import os

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-5")
N8N_BASE_URL = os.getenv("N8N_BASE_URL")
N8N_API_KEY = os.getenv("N8N_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
)
WORKFLOWGPT_API_KEY = os.getenv("WORKFLOWGPT_API_KEY")


def missing_settings() -> list[str]:
    """Names of required .env values that are still empty. Values are never returned."""
    required = {
        "LLM_API_KEY": LLM_API_KEY,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
        "N8N_BASE_URL": N8N_BASE_URL,
        "N8N_API_KEY": N8N_API_KEY,
    }
    return [name for name, value in required.items() if not (value or "").strip()]
