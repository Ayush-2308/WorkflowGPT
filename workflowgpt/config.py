import os

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER")
N8N_BASE_URL = os.getenv("N8N_BASE_URL")
N8N_API_KEY = os.getenv("N8N_API_KEY")
