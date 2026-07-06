import logging

try:
    from markdown2 import markdown
except ImportError:
    markdown = None

from odoo import _
from odoo.exceptions import UserError
from odoo.tools import html_sanitize

from odoo.addons.ai.utils.llm_api_service import LLMApiService
from odoo.addons.ai.utils import llm_providers
from odoo.addons.ai.models.ai_agent import AIAgent
from odoo.addons.ai.models.ir_actions_server import IrActionsServer

from odoo.addons.ai_provider_opencode.models.chat_completion_provider import (
    ChatCompletionProvider,
)

_logger = logging.getLogger(__name__)

# ── 0. Patch _post_ai_response to fix bus notification ───────────

_original_post_ai_response = AIAgent._post_ai_response


def _patched_post_ai_response(self, channel, message):
    formatted_message = message
    if markdown:
        raw_html = markdown(message, extras=["fenced-code-blocks", "tables", "strike"])
        formatted_message = html_sanitize(raw_html)
    else:
        formatted_message = html_sanitize(message)
    channel.sudo().message_post(
        author_id=self.partner_id.id,
        body=formatted_message,
        message_type="comment",
        silent=False,
        subtype_xmlid="mail.mt_comment",
    )


AIAgent._post_ai_response = _patched_post_ai_response

# ── 1. Register the Opencode Go provider ─────────────────────────

llm_providers.PROVIDERS.append(
    llm_providers.Provider(
        "opencode_go",
        "Opencode Go",
        "",
        [
            ("deepseek-v4-flash", "DeepSeek V4 Flash"),
            ("deepseek-v4-pro", "DeepSeek V4 Pro"),
            ("kimi-k2.7-code", "Kimi K2.7 Code"),
            ("kimi-k2.6", "Kimi K2.6"),
            ("glm-5.2", "GLM-5.2"),
            ("glm-5.1", "GLM-5.1"),
            ("mimo-v2.5", "MiMo-V2.5"),
            ("mimo-v2.5-pro", "MiMo-V2.5 Pro"),
            ("minimax-m3", "MiniMax M3"),
            ("minimax-m2.7", "MiniMax M2.7"),
            ("qwen3.7-max", "Qwen3.7 Max"),
            ("qwen3.7-plus", "Qwen3.7 Plus"),
            ("qwen3.6-plus", "Qwen3.6 Plus"),
        ],
    )
)

# ── 2. Patch LLMApiService.__init__ ────────────────────────────────

_original_init = LLMApiService.__init__


def _patched_init(self, env, provider="openai"):
    if provider in ("opencode_go",):
        self.provider = provider
        self.env = env
        icp = env["ir.config_parameter"].sudo()
        base_url = icp.get_param(
            "ai_provider_opencode.base_url",
            "https://opencode.ai/zen/go/v1",
        )
        self.base_url = base_url
        self._chat_provider = ChatCompletionProvider(env, base_url)
    else:
        _original_init(self, env, provider)


LLMApiService.__init__ = _patched_init

# ── 3. Patch _request_llm dispatch ──────────────────────────────

_original_request_llm = LLMApiService._request_llm


def _patched_request_llm(self, *args, **kwargs):
    if self.provider in ("opencode_go",):
        return self._chat_provider.single_turn(*args, **kwargs)
    return _original_request_llm(self, *args, **kwargs)


LLMApiService._request_llm = _patched_request_llm

# ── 4. Patch _build_tool_call_response ─────────────────────────

_original_build_tool_call_response = LLMApiService._build_tool_call_response


def _patched_build_tool_call_response(self, tool_call_id, return_value):
    if self.provider in ("opencode_go",):
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": str(return_value),
        }
    return _original_build_tool_call_response(self, tool_call_id, return_value)


LLMApiService._build_tool_call_response = _patched_build_tool_call_response

# ── 5. Patch get_embedding ──────────────────────────────────────

_original_get_embedding = LLMApiService.get_embedding


def _patched_get_embedding(self, *args, **kwargs):
    if self.provider in ("opencode_go",):
        _logger.info("Embeddings not available for Opencode Go provider.")
        return {"object": "list", "data": [], "model": "", "usage": {}}
    return _original_get_embedding(self, *args, **kwargs)


LLMApiService.get_embedding = _patched_get_embedding
# ── 6. Patch get_transcription ──────────────────────────────────


_original_get_transcription = LLMApiService.get_transcription


def _patched_get_transcription(self, *args, **kwargs):
    if self.provider in ("opencode_go",):
        raise UserError(
            _("Audio transcription is not available for the Opencode Go provider.")
        )
    return _original_get_transcription(self, *args, **kwargs)


LLMApiService.get_transcription = _patched_get_transcription

# ── 7. Patch get_transcription_session ──────────────────────────


_original_get_transcription_session = LLMApiService.get_transcription_session


def _patched_get_transcription_session(self, *args, **kwargs):
    if self.provider in ("opencode_go",):
        raise UserError(
            _("Realtime audio sessions are not available for the Opencode Go provider.")
        )
    return _original_get_transcription_session(self, *args, **kwargs)


LLMApiService.get_transcription_session = _patched_get_transcription_session

# ── 8. Patch _ai_tool_search for clean error messages ────────

_original_tool_search = AIAgent._ai_tool_search


def _patched_tool_search(self, model_name, domain="", fields=None, offset=0, limit=None, order=None):
    try:
        return _original_tool_search(self, model_name, domain, fields, offset, limit, order)
    except ValueError as e:
        err = str(e)
        if "Invalid field" in err or "field" in err.lower():
            import re
            match = re.search(r"'([^']+)'", err)
            bad_field = match.group(1) if match else "?"
            _logger.warning(
                "[OC] Tool search error on '%s': invalid field '%s', "
                "sending clean error to AI", model_name, bad_field
            )
            raise ValueError(
                _("Field '%(field)s' does not exist on '%(model)s'. "
                  "Use get_fields(%(model)s) to see available fields, "
                  "then retry with valid fields only.",
                  field=bad_field, model=model_name)
            )
        raise


AIAgent._ai_tool_search = _patched_tool_search

# ── 9. Patch _ai_tool_read_group for clean error messages ────

_original_tool_read_group = AIAgent._ai_tool_read_group


def _patched_tool_read_group(self, model_name, domain, groupby=None, aggregates=None, having="[]", offset=0, limit=None, order=None):
    try:
        return _original_tool_read_group(self, model_name, domain, groupby, aggregates, having, offset, limit, order)
    except ValueError as e:
        err = str(e)
        if "Invalid field" in err:
            import re
            match = re.search(r"'([^']+)'", err)
            bad_field = match.group(1) if match else "?"
            _logger.warning(
                "[OC] Tool read_group error on '%s': invalid field '%s', "
                "sending clean error to AI", model_name, bad_field
            )
            raise ValueError(
                _("Field '%(field)s' is not valid on '%(model)s'. "
                  "Use get_fields(%(model)s) to see available fields.",
                  field=bad_field, model=model_name)
            )
        raise


AIAgent._ai_tool_read_group = _patched_tool_read_group

# ── 10. Patch _ai_tool_get_fields: grouped format + mode/filter ──

_original_tool_get_fields = AIAgent._ai_tool_get_fields


def _patched_tool_get_fields(self, model_name, include_description=True, **kwargs):
    mode = kwargs.get('mode', self.env.context.get('ai_get_fields_mode', 'all'))
    filter_val = kwargs.get('filter', self.env.context.get('ai_get_fields_filter'))

    if not isinstance(model_name, str):
        raise TypeError("Model name must be a string.")
    if not model_name:
        raise ValueError("Model name must be provided.")
    if model_name not in self.env:
        raise ValueError(f"Model '{model_name}' not found.")

    model = self.env[model_name]
    model_fields = model.fields_get()

    filter_lower = filter_val.lower() if filter_val else None

    selection_fields = []
    relation_fields = []
    other_fields = []

    for field_name, field_info in model_fields.items():
        if not model._fields[field_name]._description_searchable:
            continue
        field_type = field_info.get('type', 'unknown')
        field_display_name = field_info.get('string', '')
        field_relation = field_info.get('relation', '')

        if filter_lower:
            matched = (
                filter_lower in field_name.lower()
                or filter_lower in field_display_name.lower()
            )
            if not matched and field_type == 'selection':
                selection_items = field_info.get('selection', [])
                matched = any(
                    filter_lower in str(k).lower() or filter_lower in str(v).lower()
                    for k, v in selection_items
                )
            if not matched:
                continue

        if field_type == 'selection':
            selection_items = field_info.get('selection', [])
            options = [str(v or k) for k, v in selection_items]
            keys = [str(k) for k, v in selection_items]
            selection_fields.append((field_name, field_display_name, options, keys))
        elif field_relation:
            relation_fields.append((field_name, field_display_name, field_type, field_relation))
        else:
            other_fields.append((field_name, field_display_name, field_type))

    if mode == "selection":
        if not selection_fields:
            return "No filter/selection fields found."
        lines = [f"## Filter fields ({len(selection_fields)})"]
        for name, display, options, keys in selection_fields:
            lines.append(f"  {name} ({display}) → [{', '.join(options)}]")
            first_key = keys[0] if keys else ''
            lines.append(f"    → search(\"{model_name}\", [[\"{name}\", \"=\", \"<value>\"]])")
        return "\n".join(lines)

    lines = []
    if filter_val:
        total = len(selection_fields) + len(relation_fields) + len(other_fields)
        lines.append(f"## Fields matching '{filter_val}' ({total})")

    if selection_fields:
        lines.append(f"## Filter fields ({len(selection_fields)})")
        for name, display, options, keys in selection_fields:
            lines.append(f"  {name} ({display}) → [{', '.join(options)}]")
            lines.append(f"    → search(\"{model_name}\", [[\"{name}\", \"=\", \"<value>\"]])")

    if relation_fields:
        if selection_fields:
            lines.append("")
        lines.append(f"## Related models ({len(relation_fields)})")
        for name, display, ftype, relation in relation_fields:
            lines.append(f"  {name} ({display}) → {relation}")

    if other_fields:
        if selection_fields or relation_fields:
            lines.append("")
        lines.append(f"## Other fields ({len(other_fields)})")
        for name, display, ftype in other_fields:
            lines.append(f"  {name} ({display}:{ftype})")

    return "\n".join(lines)


AIAgent._ai_tool_get_fields = _patched_tool_get_fields

# ── 11. Patch _get_ai_tools: inject mode/filter into schema ──

_original_get_ai_tools = IrActionsServer._get_ai_tools


def _patched_get_ai_tools(self, record=None, tool_calls_history=None):
    tools = _original_get_ai_tools(self, record, tool_calls_history)
    if "ir_actions_server_get_fields" in tools:
        desc, allow_end, exec_fn, schema = tools["ir_actions_server_get_fields"]
        schema = dict(schema)
        schema["properties"] = dict(schema.get("properties", {}))
        schema["properties"]["mode"] = {
            "type": "string",
            "enum": ["all", "selection"],
            "description": "'all' (default) returns all searchable fields grouped by category (filter fields first). 'selection' returns only filter/selection fields for quick domain construction.",
        }
        schema["properties"]["filter"] = {
            "type": "string",
            "description": "Optional keyword to narrow results. Only returns fields whose name, label, or selection options contain this term. Example: filter='retail' returns only fields related to 'retail'.",
        }
        tools["ir_actions_server_get_fields"] = (desc, allow_end, exec_fn, schema)
    return tools


IrActionsServer._get_ai_tools = _patched_get_ai_tools

# ── 12. Patch _ai_tool_run: bridge mode/filter to env.context ──

_original_ai_tool_run = IrActionsServer._ai_tool_run


def _patched_ai_tool_run(self, record, arguments):
    extra_ctx = {}
    for key in ('mode', 'filter'):
        if key in arguments:
            extra_ctx[f'ai_get_fields_{key}'] = arguments.pop(key)
    if extra_ctx and record:
        try:
            record = record.with_context(**extra_ctx)
        except Exception:
            pass
    return _original_ai_tool_run(self, record, arguments)


IrActionsServer._ai_tool_run = _patched_ai_tool_run