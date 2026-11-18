# AI Module — Odoo AI

> **Module:** `ai` (+ about 55 satellite modules) | **Path:** [`enterprise/ai/`](../enterprise/ai/)
> Verified against Odoo 20 source on 2026-09-24.

## What It Does & Why It Exists

`ai` is the central AI layer of Odoo Enterprise (license OEEL-1). Every AI feature in the other apps goes through it:

1. **Agents** (`ai.agent`) — assistants with a prompt, skills and knowledge sources that users chat with in Discuss, in a record's side panel, from the systray, or as livechat operators.
2. **AI server actions** (`ir.actions.server`, `state='ai'`) — an automation step that hands a record and a prompt to the model and lets it call other server actions as tools.
3. **AI fields** ([`ai_fields`](../enterprise/ai_fields/)) — fields whose value is written by the model from the record's data, used by Studio and several apps.
4. **Writing helpers** — "Write an email", "Rewrite content", chatter and file-viewer help, AI prompt blocks inside mail templates, image generation, voice transcription.
5. **MCP server** ([`ai_mcp`](../enterprise/ai_mcp/)) — lets external AI clients (Claude, ChatGPT, Grok) query Odoo.

All model calls go to **Odoo AI**, an IAP paid service ([`iap_service_odoo_ai`](../enterprise/ai/data/iap_service_data.xml#L4); the manifest sets [`iap_paid_service`](../enterprise/ai/__manifest__.py#L80)). Usage consumes IAP credits of the `odoo_ai` account. There is **no bring-your-own-key**: no provider, model or API-key setting exists in the database. Odoo AI decides which upstream model answers.

---

## The Big Picture — How a Request Flows

```
Agent chat (async)                                  One-shot calls (sync)
------------------                                  ---------------------
user message in an ai_chat channel                  AI server action / AI field / composer button
   |                                                   |
   v                                                   v
ai.session._save_and_submit_request                 ai.session._get_direct_response
   |  POST /api/odoo_ai/1/get_completions              |  loop: POST /api/odoo_ai/1/get_completions_sync
   |  with webhook_url + HMAC secret                   |    tool calls -> run ir.actions.server tools
   v                                                   |    repeat until a text answer (max 30 rounds)
Odoo AI (https://ai.api.odoo.com)                      v
   |  calls back /ai/completion_result_ready        answer returned to the caller
   v
ai.session._continue_agent_loop
   |  tool calls -> confirm / run tools -> next round
   v
answer posted in the channel as the agent's partner
```

- **Transport** — [`call_odoo_ai`](../enterprise/ai/utils/ai_utils.py#L109) posts to `<endpoint>/api/odoo_ai/<route>` with the IAP account token and database UUID. The endpoint defaults to [`https://ai.api.odoo.com`](../enterprise/ai/utils/ai_utils.py#L70) and can be changed with the ICP `ai.endpoint`.
- **Chat is asynchronous** — [`_save_and_submit_request`](../enterprise/ai/models/ai_session.py#L470) stores the request on `ai.session`, submits it after commit, and waits in `loop_state='waiting_model'`. Odoo AI posts the result to [`completion_result_ready`](../enterprise/ai/controllers/thread.py#L142), a public route that checks an HMAC signature before resuming the session.
- **One-shot calls are synchronous** — [`_run_agentic_loop`](../enterprise/ai/models/ai_session.py#L1194) calls [`1/get_completions_sync`](../enterprise/ai/models/ai_session.py#L1265) and runs tool calls in-process.

### Where AI shows up — same pipe, different callers

| Caller | Tools | History | Path |
|---|---|---|---|
| Agent chat (`ai.agent`) | The agent's skills | Yes (the session's messages) | Async, webhook |
| AI server action | `ai_tool_ids` of the action | No | Sync ([`_ai_action_run`](../enterprise/ai/models/ir_actions_server.py#L207)) |
| AI field | None — output forced to the field's JSON schema, web grounding on | No | Sync ([ai_fields_tools.py](../enterprise/ai/utils/ai_fields_tools.py#L160)) |
| Composer / prompt buttons | The agent's default tools | No | Sync, `/ai/get_direct_response` |
| Scheduled agent automation (`ai_agentic`) | The agent's skills, auto-confirmed | Kept in a chat for inspection | Via `base.automation` |

---

## Agents, Skills and Tools

### `ai.agent` — the assistant

[ai_agent.py](../enterprise/ai/models/ai_agent.py#L43). Each agent owns a hidden `res.partner` so it can author messages.

- **`system_prompt`** — the agent's instructions.
- **`skill_ids`** — what it can do. New agents start with the native skills ([`skill_ids`](../enterprise/ai/models/ai_agent.py#L63)).
- **`sources_ids`** + **`restrict_to_sources`** — knowledge for RAG, and whether it may answer only from it ([`restrict_to_sources`](../enterprise/ai/models/ai_agent.py#L58)).
- **`allowed_agent_ids`** — other agents it may delegate to; delegation runs as a child `ai.session` ([`allowed_agent_ids`](../enterprise/ai/models/ai_agent.py#L80)).
- **`embedding_model`** — set from Odoo AI's default when the agent is created.
- The shipped **Odoo AI** agent ([data](../enterprise/ai/data/ai_agent_data.xml#L3)) is a system agent and cannot be deleted ([`_unlink_except_system_agent`](../enterprise/ai/models/ai_agent.py#L141)).

### `ai.skill` — instructions plus tools

[ai_skill.py](../enterprise/ai/models/ai_skill.py#L6). A skill is a block of instructions and optional tools (`tool_ids`, server actions with `use_in_ai`). With tools it is "executable", without it is "guidance". Shipped skills: Shape View, Search Database, Update Records, Create Records, Generate Image, Web Search ([ai_skill_data.xml](../enterprise/ai/data/ai_skill_data.xml#L3)). Native skills (Generate Image, Web Search) cannot be edited or deleted. Removing a skill from an agent clears the tool state of its open sessions.

`ai.topic` does not exist in 20.0; use `ai.skill`.

### Tools — server actions the model may call

A tool is an `ir.actions.server` with **Use in AI** ([`use_in_ai`](../enterprise/ai/models/ir_actions_server.py#L83)), an `ai_tool_name`, a description and, for code actions, a JSON schema for its arguments. The ORM helpers live on the abstract [`ai.tool`](../enterprise/ai/models/ai_tool.py#L53).

- Tools run **with the user's rights**: the evaluation context uses a non-sudo environment ([`_ai_tool_run`](../enterprise/ai/models/ir_actions_server.py#L298)).
- **Create Records** and **Update Records** stop and show a confirmation preview before writing ([update](../enterprise/ai/models/ai_tool.py#L1008), [create](../enterprise/ai/models/ai_tool.py#L1114)), unless the session is set to auto-confirm.
- The generic record tools refuse every `ir.*` model (reading `ir.ui.menu` and `ir.attachment` excepted) and `base.automation`, `res.device`, `res.groups`, `res.groups.privilege`, `res.users.settings` ([`_check_agent_model_access`](../enterprise/ai/models/ai_tool.py#L96), [`AI_MODELS_BLOCKLIST`](../enterprise/ai/utils/ai_utils.py#L31)).
- Limits: `ai.max_successive_calls` (30 model rounds per request) and `ai.max_tool_calls_per_call` (20 tool calls per round; the rest are returned as "Not executed").

### `ai.session` — the conversation state

[ai_session.py](../enterprise/ai/models/ai_session.py#L82). One session per chat (child sessions for delegation). `loop_state` tells where it waits: model, user confirmation, user answer, client result, external result or child session ([`loop_state`](../enterprise/ai/models/ai_session.py#L103)). Session options: web search, "think longer", restrict to sources, show agent steps, auto-confirm.

---

## RAG — Sources and Embeddings

- **Sources** (`ai.agent.source`): files and URLs; `ai_documents_source` adds Documents, `ai_knowledge` adds Knowledge articles ([`type`](../enterprise/ai/models/ai_agent_source.py#L21)). Each source shows a status (processing, indexed, incomplete, failed, skipped) and can be switched off.
- **Chunks and vectors** (`ai.embedding`): 1536-dimension pgvector column with an HNSW cosine index ([`embedding_vector`](../enterprise/ai/models/ai_embedding.py#L39)). Embeddings are computed through Odoo AI by crons ([ir_cron.xml](../enterprise/ai/data/ir_cron.xml#L5)); a credit failure marks the chunk `iap_credit_error`.
- **Retrieval** ([`_build_rag_context`](../enterprise/ai/models/ai_agent.py#L206)): the prompt is embedded and the **top 5 chunks with cosine similarity ≥ 0.9** are added to the context ([`_get_similar_chunks`](../enterprise/ai/models/ai_embedding.py#L43)). Weakly related chunks are dropped, not ranked lower.
- **Embedding model** — chosen by Odoo AI ([`_get_default_embedding_model`](../enterprise/ai/models/ai_embedding.py#L224)). A daily cron moves chunks and agents off embedding models Odoo AI has deprecated and re-embeds them ([`_cron_update_deprecated_embedding_models`](../enterprise/ai/models/ai_embedding.py#L283)).
- **pgvector is mandatory.** The `ai` pre-init hook creates the `vector` extension or aborts the install ([`pgvector_is_available`](../enterprise/ai/__init__.py#L20)). `ai_auto_install` (auto-installed with `mail`) installs `ai` only when that succeeds ([ai_auto_install](../enterprise/ai_auto_install/__init__.py#L6)).

---

## Module Map

| Module | Role |
|---|---|
| `ai` | Core: agents, skills, tools, sessions, embeddings, composer, transcription, AI server actions. Depends on `mail` and `iap` |
| `ai_agentic` | The **AI** app (menus Agents; Configuration → Skills, Tools, Default Prompts) and scheduled agent automations on `base.automation` ([`ai_agent_id`](../enterprise/ai_agentic/models/base_automation.py#L17)). Not auto-installed |
| `ai_auto_install` | Installs `ai` when pgvector is available |
| `ai_fields`, `ai_server_actions`, `web_studio_ai_fields` | AI fields, AI field updates in server actions, Studio UI |
| `ai_mcp` | MCP server at `/mcp` with OAuth (auto-installed with `ai`) |
| `ai_livechat`, `ai_website_livechat` and `ai_website_*_livechat` | Agents as livechat operators, per website channel |
| `ai_documents`, `ai_documents_source`, `ai_knowledge`, `ai_agentic_documents`, `ai_agentic_knowledge` | Document sorting, Documents and Knowledge as agent sources |
| `ai_crm`, `ai_account`, `ai_account_reports`, `ai_sale`, `ai_purchase`, `ai_stock`, `ai_project`, `ai_product`, `ai_helpdesk`, `ai_calendar`, `ai_timesheet_grid`, `ai_mass_mailing`, `ai_social`, `ai_esg`, `ai_marketing_automation*` | App-specific prompts, tools and skills |
| `ai_website`, `ai_html_builder`, `ai_cloud_storage` | Website and editor features, cloud-stored sources |
| `voip_ai`, `sign_ai`, `hr_recruitment_ai` | Call transcription, Sign and Recruitment helpers |

Every satellite except `ai_agentic` and the test modules is auto-installed when its dependencies are present. `ai_app` and `esg_csrd_ai` do not exist in 20.0; the AI app is `ai_agentic`, ESG uses `ai_esg`.

Integration points in core models:

- **`discuss.channel`**: `channel_type='ai_chat'` and `ai_agent_id` (`groups=NO_ACCESS`, only sudo code writes it) ([discuss_channel.py](../enterprise/ai/models/discuss_channel.py#L17)).
- **`mail.render.mixin`**: AI prompt blocks in templates are evaluated at render time when `eval_ai_prompts` is set ([mail_render_mixin.py](../enterprise/ai/models/mail_render_mixin.py#L22)).
- **`ir.actions.server`**: `state='ai'`, tool metadata ([`state`](../enterprise/ai/models/ir_actions_server.py#L49)).
- **`ai.composer`**: which agent and default prompt serve each entry point — HTML field, mail composer, text selection, chatter, systray, voice transcription, file viewer, media dialog ([`INTERFACE_KEYS`](../enterprise/ai/models/ai_composer.py#L11)).

---

## Configuration

There is no AI settings page for keys or models. What you configure:

- **Credits** — the Odoo AI IAP account; running out raises "Not enough credits to use Odoo AI" and sends a notification.
- **AI app** (`ai_agentic`) — agents, skills, tools (administrators), default prompts per entry point.
- **System parameters** — `ai.endpoint`, `ai.max_successive_calls` (30), `ai.max_tool_calls_per_call` (20), `ai.max_transcription_retries` (5, seeded).
- **MCP** (Settings, `ai_mcp`) — **Dynamic Client Registration** (ICP `enable_dcr`, off) and **Allowed Client ID Metadata Documents** (ICP `cimd_allowed_urls`) ([res_config_settings.py](../enterprise/ai_mcp/models/res_config_settings.py#L8)).

**Access** ([ir.access.csv](../enterprise/ai/security/ir.access.csv)): internal users read agents, skills, composers, prompt buttons and sources; only `base.group_system` creates or edits them. A skill's tools are visible to administrators only. The AI app menu requires `base.group_user_regular`, so light users do not see it.

---

## Claude, Anthropic and Other LLMs

**Inside Odoo there is no provider choice for anyone.** Odoo AI selects the upstream models; code comments refer to OpenAI and Gemini behavior ([validators.py](../enterprise/ai/utils/tools_schema/validators.py#L84)), and live voice transcription opens a browser WebSocket straight to OpenAI's realtime API with a short-lived token from Odoo AI ([realtime_client.js](../enterprise/ai/static/src/core/realtime_client.js#L35)). No Anthropic path exists, and no customer key can be supplied for any vendor. `LLMApiService`, `llm_providers.PROVIDERS`, `ai.openai_key` and `ai.google_key` do not exist in 20.0.

**The supported way to use Claude with Odoo is the MCP server** ([`ai_mcp`](../enterprise/ai_mcp/__manifest__.py#L18)):

- **Endpoint** `https://<odoo>/mcp`, bearer-authenticated with scope `mcp` ([mcp_controller.py](../enterprise/ai_mcp/controllers/mcp_controller.py#L19)). Two ways in: an API key generated with the MCP scope (user avatar → Security), or OAuth — Odoo acts as the authorization server (discovery, consent, token and revoke routes in [oauth_server_controller.py](../enterprise/ai_mcp/controllers/oauth_server_controller.py#L24)).
- **Client identification** — clients publishing a Client ID Metadata Document are accepted when their URL is allowlisted; the seeded list contains ChatGPT, claude.ai MCP, Claude Code and Grok ([data](../enterprise/ai_mcp/data/ir_config_parameter_data.xml#L8)). Dynamic Client Registration is off by default.
- **Tools** — shipped MCP tools are read-only: list models, list fields, search, read_group, and an initial-context tool (user, timezone, companies) ([data](../enterprise/ai_mcp/data/ir_actions_server_data.xml#L3)). An administrator can expose other eligible server actions with **Available in MCP** and must flag **Readonly Tool** truthfully ([`use_in_mcp`](../enterprise/ai_mcp/models/ir_actions_server.py#L10)).
- **Rights** — calls run as the token's user after `_can_execute_action_on_records`. They are sent with `tool_request_confirmed=True` ([`_mcp_tools_call`](../enterprise/ai_mcp/models/ai_mcp_request_dispatcher.py#L67)): a write tool exposed to MCP runs without Odoo's confirmation preview, so the MCP client's own approval step is the only gate.

Pointing `ai.endpoint` at a self-hosted service that speaks Odoo AI's private `/api/odoo_ai/1/*` protocol would be the only way to change the in-Odoo model [Guessing — the protocol is undocumented and not in this source].

---

## Edge Cases & Gotchas

- **Agent chat needs an Internet-reachable Odoo.** Odoo AI calls back `web.base.url` + `/ai/completion_result_ready`. Behind NAT or a firewall, chats stay "Waiting for Model"; no code times a waiting session out. One-shot features (AI fields, server actions, composer buttons) work without the callback.
- **Web grounding and tools do not mix.** A one-shot call with both raises an error; use the Web Search skill instead ([`_run_agentic_loop`](../enterprise/ai/models/ai_session.py#L1194)).
- **AI chat channels are garbage-collected** after 30 days without activity, or after 1 day if they hold no message ([`_remove_ai_chat_channels`](../enterprise/ai/models/discuss_channel.py#L57)).
- **AI fields fill in the background.** A daily cron computes empty AI fields in batches ([`_cron_fill_ai_fields`](../enterprise/ai_fields/models/ir_model_fields.py#L141)); saving a field's prompt triggers it. Its comment about "the openAI key" is stale — there is no key.
- **AI server actions log their tool calls** in the record's chatter under an AI author.
- **Scheduled agent automations auto-confirm tool calls** — the agent can create and update records without a preview; each run is kept in a chat.
- **High RAG threshold** — with similarity ≥ 0.9, loosely phrased questions often get no source chunk.
- **Live voice audio goes from the browser to OpenAI**, not through the Odoo server; recorded calls are transcribed through Odoo AI (`1/get_transcription`).

## Related Docs

- [`INDEX.md`](INDEX.md)
