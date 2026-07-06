# AI Provider — Opencode Go

Odoo Enterprise AI is powerful — but out of the box it only speaks to OpenAI and Google Gemini. Your data leaves your network, you pay per token on someone else's meter, and you can't pick the model. If you self-host, care about data privacy, or already run your own LLM infrastructure, that's a frustrating lock-in.

This module tears down that wall. It lets Odoo's AI agents talk to **any** OpenAI-compatible API — including [Opencode Go](https://opencode.ai), Ollama, vLLM, LocalAI, or your own custom proxy — without modifying a single enterprise file.

**Bring Your Own Key (BYOK).** Or Bring Your Own Kubernetes. Use the model you want (DeepSeek, Llama, Mistral, Qwen2.5, whatever), run it where you want (on-prem, VPC, or a budget cloud endpoint), and pay your own infrastructure cost instead of per-token markups. No vendor lock, no data exfiltration, no surprises.

> **What is Opencode Go?** A free, OpenAI-compatible API proxy that exposes models like DeepSeek V4 Flash. You can point this module at it in 30 seconds — or at any other endpoint that speaks `/v1/chat/completions`.

This module is for system integrators, self-hosters, and anyone who wants Odoo AI on their own terms. It works via 12 monkey-patches — no enterprise `.py` files are touched, so upgrades won't overwrite your changes.

---

## How it works

```
User → Odoo AI Agent → LLMApiService → ChatCompletionProvider → /v1/chat/completions
                                    ↕
                             12 monkey-patches
```

| Layer | Component | Lines | Role |
|---|---|---|---|
| API translation | `ChatCompletionProvider` | 380 | Converts Odoo's Responses API ↔ Chat Completions API |
| Provider registration | Patch #1 | — | Registers `opencode_go` in `llm_providers.PROVIDERS` |
| Dispatch | Patches #2–7 | — | Route requests to provider, stub unsupported features |
| Tool output quality | Patches #8–12 | — | Grouped formats, clean errors, mode/filter params |
| Bus notification | Patch #0 | — | Real-time reply visibility |
| JS fix | `composer_patch_fix.js` | 21 | Fix `web_tour` crash in AI chat composer |

### File map

```
addons/ai_provider_opencode/
├── __init__.py
├── __manifest__.py
├── README.md
├── data/
│   └── ai_available_model_data.xml        # 13 default model records
├── models/
│   ├── __init__.py
│   ├── ai_available_model.py              # Model registry (32 lines)
│   ├── chat_completion_provider.py        # Core API translation (380 lines)
│   ├── llm_patches.py                     # All 12 monkey-patches (365 lines)
│   └── res_config_settings.py             # Settings fields (45 lines)
├── security/
│   └── ir.model.access.csv
├── static/src/
│   └── composer_patch_fix.js              # JS for composer focus bug
└── views/
    └── res_config_settings_views.xml
```

## The 12 Patches

| # | Method patched | What it does |
|---|---|---|
| **0** | `AIAgent._post_ai_response` | Set `silent=False` so AI replies appear without page refresh |
| **1** | `llm_providers.PROVIDERS` | Register `opencode_go` provider with 13 model options |
| **2** | `LLMApiService.__init__` | Intercept `opencode_go` — read base URL + key from config, init `ChatCompletionProvider` |
| **3** | `LLMApiService._request_llm` | Dispatch to `ChatCompletionProvider.single_turn()` |
| **4** | `LLMApiService._build_tool_call_response` | Return Chat Completions tool format `{role:"tool", tool_call_id, content}` |
| **5** | `LLMApiService.get_embedding` | Return empty (embeddings not supported) |
| **6** | `LLMApiService.get_transcription` | Raise `UserError` (not supported) |
| **7** | `LLMApiService.get_transcription_session` | Raise `UserError` (not supported) |
| **8** | `AIAgent._ai_tool_search` | Catch field errors → clean actionable message instead of raw traceback |
| **9** | `AIAgent._ai_tool_read_group` | Same as #8 for read_group |
| **10** | `AIAgent._ai_tool_get_fields` | Grouped output (selection fields first, then relations, then others) + `mode`/`filter` params |
| **11** | `IrActionsServer._get_ai_tools` | Inject `mode` and `filter` params into tool schema so LLM discovers them |
| **12** | `IrActionsServer._ai_tool_run` | Pop `mode`/`filter` from arguments before validation, inject into record `env.context` as bridge |

## Pros vs Native Odoo AI (GPT / Gemini)

| Capability | Odoo Enterprise AI | Opencode Go |
|---|---|---|
| **Embeddings / RAG** | ✅ Full | ❌ Not supported |
| **Audio transcription** | ✅ Full | ❌ Not supported |
| **Web grounding** | ✅ Full | ❌ Not supported |
| **PDF inline** | ✅ Supported | ❌ Silently skipped |
| **Structured output** | ✅ JSON schema | ✅ Supported |
| **Image attachments** | ✅ Supported | ✅ Supported |
| **Tool calling** | ✅ Stable | ✅ Works |
| **Real-time responses** | ✅ Native | ✅ Works (patch #0) |
| **Model flexibility** | ❌ Vendor-locked (OpenAI/Google) | ✅ Any OpenAI-compatible endpoint |
| **Cost control** | ❌ Per-token billing | ✅ BYOK — use your own infra |
| **Data privacy** | ❌ Leaves your network | ✅ Can be fully on-premise |
| **Configurability** | ❌ Fixed per provider | ✅ Configurable URL, key, model, temperature |
| **Zero enterprise edits** | N/A | ✅ All via monkey-patches |

## Why Beta — Fundamental Limitations

### 1. LLM behavior is unpredictable

The model has its own reasoning that system prompts cannot fully override:

- **"List view" triggers menu-hunting** — the AI traverses the `ir.ui.menu` tree looking for an action to open, instead of using `search` to get data
- **Semantic bias overrides tool results** — "retail" makes the AI explore product-group tables even when `get_fields` clearly shows `project_job_category → [office, retail]`
- **Attention decays after 5+ rounds** — the original user query is buried under tool results; the AI starts searching unrelated models
- **Error derailment** — a single tool error (wrong field name) causes the AI to re-explore models from scratch instead of recovering with the corrected field

These are **model-level issues**, not fixable in the integration layer. Different models (GPT-4o, Claude, Gemini 2.5) would behave differently.

### 2. No access to Odoo's internal AI optimizations

The enterprise `ai` module has optimizations for OpenAI/Google that we cannot reuse:

- **Usage-based billing** — no token counters integrated with Odoo's billing
- **AI logging session details** — no access to session internals for performance timing
- **Response streaming** — Chat Completions API mode does not stream
- **Tool schema optimizations** — schemas are designed for OpenAI/Google, not generic

### 3. Monkey-patch fragility

All 12 patches operate on private enterprise methods. Future Odoo updates can silently break:

- Method renames → patches become no-ops
- Signature changes → patches raise `TypeError`
- Refactored service layer → entire pattern collapses

### 4. Context window bloat

Each tool call appends its result to the conversation. By round 10+, the context exceeds 20k tokens. The model becomes unreliable around round 8 due to attention pressure. Odoo caps at 20 successive calls, but the AI typically degrades before hitting the limit.

### 5. Token inefficiency

- `get_fields` returns **all** searchable fields when the AI only needs one or two
- `get_menu_details` returns pipe-delimited CSV that LLMs parse poorly
- The AI repeatedly re-fetches the same field data across multiple rounds

## Known Issues

| Issue | Status |
|---|---|
| Websocket binding fails first run | Workaround: `workers = 0`, `gevent_port = 8072` in config |
| AI loops on related-model field exploration | Priority rule in system reminder mitigates but doesn't eliminate |
| `mode`/`filter` params bypass enterprise schema validation | Works but fragile — relies on #12 bridge |
| PDF files silently skipped | `_logger.warning` only — no user-facing message |
| No embeddings → no RAG | Falls back silently to non-RAG mode |

## Observability

All logs are prefixed `[OC]`. Grep for debugging:

```
grep "\[OC\]" /var/log/odoo/odoo-server.log
```

Key log events:

| Pattern | What it tells you |
|---|---|
| `[OC] Tool round N` | Which iteration of the tool loop (1–20) |
| `[OC] Injected objective reminder: '...'` | Original user query re-injected as system prompt |
| `[OC] Tokens: N prompt + M completion = T total` | Context window pressure |
| `[OC] Tool search error on 'X': invalid field 'Y'` | AI used wrong field name, clean error sent back |
| `[OC] Filter fields (N)` | Selection fields count from patched get_fields |
| `[OC] Tool round N` + stops | AI hit max successive calls or gave up |

## Setup

1. Install the module
2. Go to **Settings → General Settings → Integration**
3. Toggle **"Use Opencode Go"**
4. Enter your API key, base URL, and select a model
5. Go to **Settings → AI → Agents**
6. Create or edit an agent — set **Provider** to `Opencode Go` and select your model
7. Start chatting via the AI discuss channel

### Config reference

| Setting | Default | Parameter key |
|---|---|---|
| API Key | — | `ai_provider_opencode.api_key` / env `ODOO_AI_OPENCODE_GO_TOKEN` |
| Base URL | `https://opencode.ai/zen/go/v1` | `ai_provider_opencode.base_url` |
| Model | `deepseek-v4-flash` | `ai_provider_opencode.model` |

## Notes

- This module was tested with DeepSeek V4 Flash via Opencode Go. Other models may behave differently.
- The `ChatCompletionProvider` class is designed to work with **any** OpenAI-compatible endpoint. Point it at Ollama, vLLM, LocalAI, or a custom proxy.
- If using Ollama, ensure the model supports tool calling (e.g., `llama3.1`, `mistral`, `qwen2.5`).
- The module does **not** expose a Models API endpoint — models must be configured in General Settings and the agent configuration.
