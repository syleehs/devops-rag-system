"""
Configuration Module
Manages all configuration from environment variables and defaults
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into individual components."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query or "")
    return {
        "db_name": parsed.path.lstrip("/"),
        "db_user": parsed.username or "",
        "db_password": parsed.password or "",
        "db_host": parsed.hostname or "localhost",
        "db_port": parsed.port or 5432,
        "db_sslmode": qs.get("sslmode", ["prefer"])[0],
    }


@dataclass
class Config:
    """
    Application configuration.

    Supports two modes:
    - DATABASE_URL (single connection string — used by Neon, Supabase, Fly.io, Railway)
    - Individual DB_* vars (legacy — used by local docker-compose and AWS RDS)
    """

    # Database — DATABASE_URL takes precedence over individual vars
    database_url: str = os.getenv("DATABASE_URL", "")
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    db_host: str = ""
    db_port: int = 5432
    db_sslmode: str = "prefer"

    # LLM Provider (Groq via OpenAI-compatible API)
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    # Cost per 1M tokens (defaults 0 for free tier; override for paid tiers)
    llm_input_cost_per_m: float = float(os.getenv("LLM_INPUT_COST_PER_M", "0"))
    llm_output_cost_per_m: float = float(os.getenv("LLM_OUTPUT_COST_PER_M", "0"))

    # AWS (only used if CloudWatch metrics are enabled)
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")

    # Application
    environment: str = os.getenv("ENVIRONMENT", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    def __post_init__(self):
        """Parse DATABASE_URL or fall back to individual vars."""
        if self.database_url:
            parsed = _parse_database_url(self.database_url)
            self.db_name = parsed["db_name"]
            self.db_user = parsed["db_user"]
            self.db_password = parsed["db_password"]
            self.db_host = parsed["db_host"]
            self.db_port = parsed["db_port"]
            self.db_sslmode = parsed["db_sslmode"]
        else:
            self.db_name = os.getenv("DB_NAME", "devops_rag")
            self.db_user = os.getenv("DB_USER", "postgres")
            self.db_password = os.getenv("DB_PASSWORD", "postgres")
            self.db_host = os.getenv("DB_HOST", "localhost")
            self.db_port = int(os.getenv("DB_PORT", "5432"))
            self.db_sslmode = os.getenv("DB_SSLMODE", "prefer")

        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")

    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"

    def get_db_url(self) -> str:
        """Get PostgreSQL connection URL."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}?sslmode={self.db_sslmode}"

    def __repr__(self):
        """Safe string representation (masks sensitive values)."""
        return (
            f"Config("
            f"db_host={self.db_host}, "
            f"db_name={self.db_name}, "
            f"environment={self.environment}, "
            f"sslmode={self.db_sslmode})"
        )
