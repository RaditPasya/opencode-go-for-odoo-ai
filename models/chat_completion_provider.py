import json
import logging
import os

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ChatCompletionProvider:
    """
    Translates Odoo's internal LLM interface (Responses API format)
    to the OpenAI Chat Completions API format.

    Used by LLMApiService when provider='opencode_go'.
    """

    def __init__(self, env, base_url=None, api_key=None):
        self.env = env
        self.base_url = (base_url or "https://opencode.ai/zen/go/v1").rstrip("/")
        self._api_key = api_key

    # ── Public entry point ──────────────────────────────────────

    def single_turn(
        self,
        llm_model,
        system_prompts,
        user_prompts,
        tools=None,
        files=None,
        schema=None,
        temperature=0.2,
        inputs=None,
        web_grounding=False,
    ):
        """
        Single request/response cycle.

        Returns:
            response_texts : list[str]
            tools_to_call  : list[tuple[str, str, dict]]  (name, call_id, arguments)
            next_inputs    : list[dict]
        """
        if web_grounding:
            _logger.info("Web grounding not supported in Chat Completions API; ignoring.")

        original_user_query = None
        has_tool_context = False
        for inp in (inputs or []):
            if inp.get("role") == "user" and inp.get("content"):
                original_user_query = inp["content"]
            if inp.get("role") in ("assistant", "tool") or inp.get("type") in ("function_call", "function_call_output"):
                has_tool_context = True
        if original_user_query and has_tool_context:
            reminder = (
                f"REMINDER — Your original task was: {original_user_query}. "
                "Priority rule: use 'Filter fields' (selection options) from get_fields FIRST. "
                "Only explore 'Related models' if no filter field has a matching option."
            )
            system_prompts = list(system_prompts) + [reminder]
            _logger.info("[OC] Injected objective reminder: %r", original_user_query[:100])

        completed_rounds = sum(1 for inp in (inputs or []) if inp.get("role") == "tool")
        next_round = completed_rounds + 1
        _logger.info("[OC] Tool round %d", next_round)

        messages = self._build_messages(system_prompts, user_prompts, inputs, files)
        chat_tools = self._build_tools(tools)
        body = self._build_request_body(llm_model, messages, chat_tools, schema, temperature)

        _logger.debug("[OC] Request body: %s", json.dumps(body)[:2000])

        last_user_msg = ""
        for inp in (inputs or []):
            if inp.get("role") == "user":
                last_user_msg = (inp.get("content") or "")[:300]
        if user_prompts:
            last_user_msg = user_prompts[-1][:300]

        _logger.info(
            "[OC] Request: model=%s, %d system, %d user, %d inputs, tools=%s, schema=%s",
            llm_model, len(system_prompts), len(user_prompts),
            len(inputs or []), bool(chat_tools), bool(schema),
        )
        if last_user_msg:
            _logger.info("[OC] User msg: %r", last_user_msg)

        response_body = self._call_api(body)

        usage = response_body.get("usage")
        if usage:
            _logger.info(
                "[OC] Tokens: %d prompt + %d completion = %d total",
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )

        choices = response_body.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            tool_calls_raw = msg.get("tool_calls") or []
            _logger.info(
                "[OC] Response: content=%s (%d chars), tool_calls=%d",
                bool(msg.get("content")),
                len(msg.get("content") or ""),
                len(tool_calls_raw),
            )
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                _logger.info(
                    "[OC]   -> tool_call: %s(%s)",
                    func.get("name"),
                    func.get("arguments", "{}")[:200],
                )
        else:
            _logger.warning("[OC] Response: no choices — %s", json.dumps(response_body)[:500])

        return self._parse_response(response_body)

    # ── Request building ────────────────────────────────────────

    def _build_messages(self, system_prompts, user_prompts, inputs, files):
        messages = []
        user_content_parts = []

        for prompt in system_prompts:
            messages.append({"role": "system", "content": prompt})

        if files:
            for idx, file in enumerate(files, start=1):
                part = self._file_to_content_part(idx, file)
                if part is not None:
                    user_content_parts.append(part)

        for prompt in user_prompts:
            user_content_parts.append({"type": "text", "text": prompt})

        i = 0
        input_list = inputs or []

        sys_msg_count = len([m for m in messages if m.get("role") == "system"])
        _logger.info("[OC] Build msgs: %d existing sys, processing %d inputs", sys_msg_count, len(input_list))

        while i < len(input_list):
            inp = input_list[i]
            role = inp.get("role")

            if role == "user":
                messages.append({"role": "user", "content": inp.get("content", "")})
                i += 1

            elif role == "assistant":
                messages.append({"role": "assistant", "content": inp.get("content", "")})
                i += 1

            elif role == "tool":
                content_str = str(inp.get("content", ""))
                _logger.info(
                    "[OC] Tool result: call_id=%s content=%s",
                    inp.get("tool_call_id", ""),
                    content_str[:500],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": inp.get("tool_call_id", ""),
                    "content": content_str,
                })
                i += 1

            elif inp.get("type") == "function_call_output":
                content_str = str(inp.get("output", ""))
                _logger.info(
                    "[OC] Tool result (legacy): call_id=%s content=%s",
                    inp.get("call_id", ""),
                    content_str[:500],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": inp.get("call_id", ""),
                    "content": content_str,
                })
                i += 1

            elif inp.get("type") == "function_call":
                tool_calls = []
                while i < len(input_list) and input_list[i].get("type") == "function_call":
                    fc = input_list[i]
                    args_str = fc.get("arguments", "{}")
                    if isinstance(args_str, dict):
                        args_str = json.dumps(args_str)
                    tool_calls.append({
                        "id": fc.get("call_id", ""),
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": args_str,
                        },
                    })
                    i += 1
                _logger.info(
                    "[OC] Grouped %d function_calls into 1 assistant message",
                    len(tool_calls),
                )
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                })

            else:
                i += 1

        if user_content_parts:
            if len(user_content_parts) == 1 and user_content_parts[0]["type"] == "text":
                messages.append({"role": "user", "content": user_content_parts[0]["text"]})
            else:
                messages.append({"role": "user", "content": user_content_parts})

        return messages

    def _file_to_content_part(self, idx, file):
        mimetype = file.get("mimetype", "")
        value = file.get("value", "")

        if mimetype == "text/plain":
            return {"type": "text", "text": value}

        if mimetype.startswith("image/"):
            return {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mimetype};base64,{value}",
                    "detail": "low",
                },
            }

        if mimetype == "application/pdf":
            _logger.warning(
                "PDF files are not supported in Chat Completions mode; "
                "omitting '%s'", file.get("file_ref", idx)
            )
            return None

        _logger.warning("Unsupported file mimetype '%s'; omitting.", mimetype)
        return None

    def _build_tools(self, tools):
        if not tools:
            return None

        result = []
        for name, (description, _allow_end, _exec_fn, params) in tools.items():
            tool_def = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description or "",
                    "parameters": params,
                },
            }
            result.append(tool_def)

        return result

    def _build_request_body(self, llm_model, messages, tools, schema, temperature):
        body = {
            "model": llm_model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            body["tools"] = tools
            body["parallel_tool_calls"] = True

        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": schema,
                },
            }

        return body

    # ── Response parsing ────────────────────────────────────────

    def _parse_response(self, response_body):
        choices = response_body.get("choices", [])
        if not choices:
            _logger.warning("[OC] Parse: no choices, returning empty")
            return [], [], []

        message = choices[0].get("message", {})
        content = message.get("content")
        tool_calls_raw = message.get("tool_calls", [])

        response_texts = []
        tools_to_call = []
        next_inputs = []

        if content:
            response_texts.append(content)
            _logger.info("[OC] Parse: extracted %d texts, first 150: %r", len(response_texts), content[:150])
        else:
            _logger.info("[OC] Parse: content is None/empty")

        for tc in tool_calls_raw:
            func = tc.get("function", {})
            name = func.get("name", "")
            call_id = tc.get("id", "")
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}

            tools_to_call.append((name, call_id, args))
            next_inputs.append({
                "type": "function_call",
                "name": name,
                "call_id": call_id,
                "arguments": func.get("arguments", "{}"),
            })
            _logger.info("[OC]   -> parsed tool: %s args=%s", name, json.dumps(args)[:300])

        _logger.info("[OC] Parse result: %d texts, %d tool_calls", len(response_texts), len(tools_to_call))

        return response_texts, tools_to_call, next_inputs

    # ── HTTP call ───────────────────────────────────────────────

    def _call_api(self, body):
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._get_api_key()}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=300)
        except requests.exceptions.Timeout:
            raise UserError(_("The AI request timed out. Please try again."))
        except requests.exceptions.ConnectionError:
            raise UserError(_("Could not connect to the AI provider. Check the base URL."))
        except requests.exceptions.RequestException as e:
            raise UserError(_("AI request failed: %s", str(e)))

        if resp.status_code == 401:
            raise UserError(_("Invalid API key for Opencode Go."))
        if resp.status_code == 429:
            raise UserError(_("Rate limit exceeded. Please wait and try again."))

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            detail = resp.text[:500]
            _logger.error("Chat Completions API error %s: %s", resp.status_code, detail)
            raise UserError(_("AI provider returned error (HTTP %s).", resp.status_code))

        return resp.json()

    def _get_api_key(self):
        if self._api_key:
            return self._api_key
        key = self.env["ir.config_parameter"].sudo().get_param(
            "ai_provider_opencode.api_key"
        ) or os.environ.get("ODOO_AI_OPENCODE_GO_TOKEN")
        if not key:
            raise UserError(
                _("Opencode Go API key not configured. "
                  "Set it in Settings > General Settings > Integration.")
            )
        return key
