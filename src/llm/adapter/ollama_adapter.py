"""Ollama adapter support for language model configuration, catalogs, transports, and planning.

Implements the ollama_adapter module responsibilities used by Sonex runtime flows.
Key public entry points include OllamaAdapter.
"""

from src.llm.adapter.base import DefaultAdapter


class OllamaAdapter(DefaultAdapter):
    """Represents ollama adapter.

    Encapsulates ollama adapter data and behavior used by Sonex runtime flows. Extends default adapter semantics.
    """
    provider_name = "ollama"
    ...
