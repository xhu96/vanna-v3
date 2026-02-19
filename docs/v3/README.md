# Vanna v3 Docs

- Architecture and design: `docs/v3/architecture-and-design.md`
- Implementation milestones: `docs/v3/implementation-plan.md`
- API contract (typed events): `docs/v3/api-events-v3.md`
- Migration guide: `docs/v3/migration-v2-to-v3.md`
- Contributing & testing: `CONTRIBUTING.md`

## Supported LLM Providers

| Provider      | Integration                                            | Tox Environment     |
| ------------- | ------------------------------------------------------ | ------------------- |
| Google Gemini | `vanna.integrations.google.GeminiLlmService`           | `py311-gemini`      |
| Anthropic     | `vanna.integrations.anthropic.AnthropicLlmService`     | `py311-anthropic`   |
| OpenAI        | `vanna.integrations.openai.OpenAILlmService`           | `py311-openai`      |
| Azure OpenAI  | `vanna.integrations.azureopenai.AzureOpenAILlmService` | `py311-azureopenai` |
| Ollama        | `vanna.integrations.ollama.OllamaLlmService`           | `py311-ollama`      |

## Test Suite Overview

```bash
# All unit tests (no external dependencies)
tox -e py311-unit && tox -e py311-v3-unit

# LLM integration tests (require API keys)
GEMINI_API_KEY=... tox -e py311-gemini
ANTHROPIC_API_KEY=... tox -e py311-anthropic
OPENAI_API_KEY=... tox -e py311-openai

# Database sanity tests
tox -e py311-sqlite-sanity
tox -e py311-postgres-sanity
tox -e py311-duckdb-sanity
```
