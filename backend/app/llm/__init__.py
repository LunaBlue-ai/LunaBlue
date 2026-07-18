"""In-process local LLM runtime.

This package is the only place in the codebase allowed to import
``llama_cpp`` — everything else talks to the single global
:class:`~app.llm.runtime.LlamaRuntime` created by the ``main.py`` lifespan
handler (see docs/Architecture.md, "single global LLM runtime").
"""
