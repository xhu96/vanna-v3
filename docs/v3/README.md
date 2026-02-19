# Vanna v3 Docs

- Architecture and design: `docs/v3/architecture-and-design.md`
- Implementation milestones: `docs/v3/implementation-plan.md`
- API contract (typed events): `docs/v3/api-events-v3.md`
- Migration guide: `docs/v3/migration-v2-to-v3.md`
- Contributing & testing: `CONTRIBUTING.md`

### Personalization & Profiles

- Personalization overview: `docs/v3/personalization.md`
- Glossary & ontology: `docs/v3/glossary.md`

### Skill Fabric

- SkillSpec reference: `docs/v3/skillspec-reference.md`
- Skill lifecycle & governance: `docs/v3/skill-lifecycle.md`
- Skill generation guide: `docs/v3/skill-generation.md`
- Manual skill authoring: `docs/v3/skill-authoring.md`
- Threat model: `docs/v3/threat-model.md`

## Supported LLM Providers

| Provider      | Integration                                            | Tox Environment     |
| ------------- | ------------------------------------------------------ | ------------------- |
| Google Gemini | `vanna.integrations.google.GeminiLlmService`           | `py311-gemini`      |
| Anthropic     | `vanna.integrations.anthropic.AnthropicLlmService`     | `py311-anthropic`   |
| OpenAI        | `vanna.integrations.openai.OpenAILlmService`           | `py311-openai`      |
| OpenRouter    | `vanna.integrations.openrouter.OpenRouterLlmService`   | `py311-openrouter`  |
| Azure OpenAI  | `vanna.integrations.azureopenai.AzureOpenAILlmService` | `py311-azureopenai` |
| Ollama        | `vanna.integrations.ollama.OllamaLlmService`           | `py311-ollama`      |

## Test Suite Overview

```bash
# All unit tests (no external dependencies)
tox -e py311-unit && tox -e py311-v3-unit

# Personalization & skill fabric tests
tox -e py311-personalization
tox -e py311-skills

# LLM integration tests (require API keys)
GEMINI_API_KEY=... tox -e py311-gemini
ANTHROPIC_API_KEY=... tox -e py311-anthropic
OPENAI_API_KEY=... tox -e py311-openai
OPENROUTER_API_KEY=... tox -e py311-openrouter

# Database sanity tests
tox -e py311-sqlite-sanity
tox -e py311-postgres-sanity
tox -e py311-duckdb-sanity
```
