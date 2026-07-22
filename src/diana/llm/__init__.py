"""LLM provider package — implementations of cognitive LLMProvider port."""

from diana.llm.deepseek import DeepSeekProvider
from diana.llm.fake import FakeLLM

__all__ = ["DeepSeekProvider", "FakeLLM"]
