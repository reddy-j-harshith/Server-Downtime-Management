from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables from .env at project root
load_dotenv()


class Settings(BaseModel):
	mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
	model: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
	temperature: float = float(os.getenv("MODEL_TEMPERATURE", "0.1"))
	max_tokens: int = int(os.getenv("MODEL_MAX_TOKENS", "512"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
	settings = Settings()
	if not settings.mistral_api_key:
		# We don't raise, to allow the simulator to run without network; but LLM calls will fail.
		print("[WARN] MISTRAL_API_KEY not set in environment. LLM calls will fail. Set it in .env")
	return settings


def get_llm():
	"""Return a LangChain chat model for Mistral, configured from env settings.

	Uses langchain-mistralai's ChatMistralAI wrapper for tool-calling compatibility with LangGraph.
	"""
	from langchain_mistralai import ChatMistralAI

	s = get_settings()
	llm = ChatMistralAI(
		api_key=s.mistral_api_key or None,
		model=s.model,
		temperature=s.temperature,
		max_tokens=s.max_tokens,
	)
	return llm

