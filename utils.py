"""
Shared utilities: environment loading, logging, HTTP helpers.
"""
import os
import logging
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv

# Load .env once at import
load_dotenv()


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with optional default."""
    return os.getenv(key, default)


def setup_logging(name: str = "311_triage", level: str = "INFO") -> logging.Logger:
    """Configure and return a logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


@lru_cache(maxsize=1)
def get_openai_client():
    """Cached OpenAI client."""
    from openai import OpenAI
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")
    return OpenAI(api_key=api_key)
