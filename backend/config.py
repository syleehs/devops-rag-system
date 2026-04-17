"""
Configuration Module
Manages all configuration from environment variables and defaults
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

@dataclass
class Config:
    """
    Application configuration.
    
    All values are read from environment variables with sensible defaults.
    """
    
    # PostgreSQL Database
    db_name: str = os.getenv('DB_NAME', 'devops_rag')
    db_user: str = os.getenv('DB_USER', 'postgres')
    db_password: str = os.getenv('DB_PASSWORD', 'postgres')
    db_host: str = os.getenv('DB_HOST', 'localhost')
    db_port: int = int(os.getenv('DB_PORT', '5432'))
    
    # Anthropic API
    anthropic_api_key: str = os.getenv('ANTHROPIC_API_KEY', '')
    
    # AWS Configuration
    aws_region: str = os.getenv('AWS_REGION', 'us-east-1')
    aws_access_key: Optional[str] = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_key: Optional[str] = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    # Application
    environment: str = os.getenv('ENVIRONMENT', 'development')
    log_level: str = os.getenv('LOG_LEVEL', 'INFO')
    api_port: int = int(os.getenv('API_PORT', '8000'))
    
    def __post_init__(self):
        """Validate required configuration."""
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
    
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == 'production'
    
    def get_db_url(self) -> str:
        """Get PostgreSQL connection URL."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    def __repr__(self):
        """Safe string representation (masks sensitive values)."""
        return (
            f"Config("
            f"db_host={self.db_host}, "
            f"db_name={self.db_name}, "
            f"environment={self.environment}, "
            f"aws_region={self.aws_region})"
        )
