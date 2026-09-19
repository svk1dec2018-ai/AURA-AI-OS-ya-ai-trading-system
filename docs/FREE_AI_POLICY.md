# AURA Free AI Policy

AURA distinguishes **local unmetered inference** from **cloud free tiers**.

## Default production rule

The deterministic AURA trading core does not require any LLM API.

For AI council / maintenance features, the default free path is **local Ollama**. Local models run on the owner's hardware, require no provider API key, and have no per-token service charge. Usage is naturally limited by the PC's CPU/GPU/RAM, disk and electricity.

Run:

`INSTALL_FREE_UNLIMITED_AI.cmd`

This installs/uses Ollama and pulls the AURA `balanced5` local council:

- qwen3.5:4b
- deepseek-r1:8b
- llama3.1:8b
- gemma3:4b
- phi4-mini:3.8b

The script then sets `AURA_FREE_AI_PRESET=balanced5` in the private `.env.local`.

## Why cloud APIs are not called unlimited

AURA does **not** label a cloud API "unlimited free" unless the provider explicitly guarantees that property.

Current cloud services such as OpenRouter Free, Gemini free tier, Groq free access and Hugging Face free credits publish request/token/day or credit limits. They can be useful optional fallbacks, but they are not the zero-limit foundation of AURA.

Therefore:

- local Ollama = default free/unmetered AI
- cloud free tier = optional, quota/rate limited
- paid OpenAI = optional only
- no AI provider gets execution or risk-bypass authority

## Test isolation

Repository verification intentionally clears runtime AI environment variables before pytest. Unit tests never call real Ollama/OpenAI/cloud endpoints. After tests complete, the setup script restores the user's runtime environment.

This keeps production configuration and deterministic software verification separate.
