"""Brain 2 - LLM narrator.

Wraps LiteLLM so we can point at Ollama for a zero-cost local default
and swap to OpenAI / Anthropic / Google via config when the user opts
in. Every generated narrative passes through the safety module before
it reaches the user.
"""
