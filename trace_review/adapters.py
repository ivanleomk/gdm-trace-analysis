"""Streaming multi-format trace ingestion & pluggable adapter registry.

Built-in adapters:
  - atif:       Harbor Agent Trajectory Interchange Format (ATIF-v1.x)
  - openai:     OpenAI Chat Completions / Assistants messages + tool_calls
  - anthropic:  Anthropic Messages API content blocks (tool_use / tool_result)
  - otel:       OpenTelemetry / OpenInference / Langfuse span lists
  - mapping:    Declarative JSON dot-path adapter for novel custom formats
  - generic:    Heuristic fallback for unseen schemas
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator, Optional

from .model import CanonicalTrace, CanonicalTurn, ToolCall, ToolResult, ToolSpec
from .tool_schema import load_tool_schema_file, parse_tool_specs

HTTP_ERR_RE = re.compile(r"\bHTTP\s*([45]\d\d)\b", re.IGNORECASE)


def _try_parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s or s[0] not in "{[":
        return value
    try:
        return json.loads(s)
    except Exception:
        return value


def _classify_result_error(raw_content: Any, parsed_content: Any) -> tuple[bool, Optional[str], Optional[int]]:
    """Infer whether a tool observation represents an error, its message, and HTTP status."""
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    is_error = False

    if isinstance(parsed_content, dict):
        st = parsed_content.get("status") or parsed_content.get("status_code") or parsed_content.get("http_status")
        if isinstance(st, int):
            status_code = st
            if st >= 400:
                is_error = True
        elif isinstance(st, str):
            m = HTTP_ERR_RE.search(st)
            if m:
                status_code = int(m.group(1))
                is_error = True
            elif st.lower() in {"error", "failed", "rejected", "denied"}:
                is_error = True

        if "error" in parsed_content and parsed_content["error"] not in (None, False, ""):
            is_error = True
            err = parsed_content["error"]
            error_message = err if isinstance(err, str) else json.dumps(err, sort_keys=True)
        elif parsed_content.get("ok") is False or parsed_content.get("success") is False:
            is_error = True
            err = parsed_content.get("message") or parsed_content.get("reason") or "ok=false"
            error_message = str(err)

        if is_error and error_message is None:
            error_message = str(
                parsed_content.get("detail")
                or parsed_content.get("message")
                or parsed_content.get("reason")
                or f"status={status_code}"
            )
    elif isinstance(raw_content, str):
        m = HTTP_ERR_RE.search(raw_content)
        if m:
            status_code = int(m.group(1))
            is_error = True
            error_message = raw_content[:200]
        elif re.match(r"^\s*(error|exception|traceback|failed)\b", raw_content, re.IGNORECASE):
            is_error = True
            error_message = raw_content[:200]

    return is_error, error_message, status_code


def _parse_arguments(raw_args: Any) -> tuple[Any, Optional[str]]:
    if isinstance(raw_args, dict):
        return raw_args, None
    if raw_args is None:
        return {}, None
    if isinstance(raw_args, str):
        s = raw_args.strip()
        if not s:
            return {}, None
        try:
            parsed = json.loads(s)
            return parsed, None
        except Exception as exc:
            return raw_args, f"Invalid JSON arguments: {exc}"
    return raw_args, f"Unexpected arguments type: {type(raw_args).__name__}"


def _extract_dot_path(obj: Any, path: Optional[str]) -> Any:
    """Resolve a simple dot/index path like 'extra.outcome' or 'agent.name'."""
    if not path:
        return None
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


class TraceAdapter(ABC):
    """Base interface for converting a raw parsed record into a CanonicalTrace."""

    name: str = "base"

    @abstractmethod
    def can_parse(self, record: dict[str, Any]) -> float:
        """Return confidence in [0.0, 1.0] that this adapter handles `record`."""

    @abstractmethod
    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        """Normalize `record` into a CanonicalTrace."""


class ATIFAdapter(TraceAdapter):
    """Adapter for Harbor Agent Trajectory Interchange Format (ATIF-v1.x)."""

    name = "atif"

    def can_parse(self, record: dict[str, Any]) -> float:
        sv = str(record.get("schema_version") or "")
        if sv.upper().startswith("ATIF"):
            return 1.0
        steps = record.get("steps")
        if isinstance(steps, list) and steps:
            first = steps[0]
            if isinstance(first, dict) and "source" in first and ("step_id" in first or "observation" in first):
                return 0.9
        return 0.0

    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        trace_id = str(record.get("session_id") or record.get("trajectory_id") or fallback_id)
        agent = record.get("agent") if isinstance(record.get("agent"), dict) else {}
        tool_specs = parse_tool_specs(agent.get("tool_definitions"), source="inline:atif")
        extra = dict(record.get("extra") or {}) if isinstance(record.get("extra"), dict) else {}

        turns: list[CanonicalTurn] = []
        call_id_to_name: dict[str, str] = {}
        system_prompt: Optional[str] = None

        role_map = {
            "system": "system",
            "user": "user",
            "human": "user",
            "agent": "agent",
            "assistant": "agent",
            "tool": "tool",
        }

        for idx, step in enumerate(record.get("steps") or []):
            if not isinstance(step, dict):
                continue
            raw_source = str(step.get("source") or "event").lower()
            role = role_map.get(raw_source, raw_source)
            msg = step.get("message")
            content = msg if isinstance(msg, str) else (json.dumps(msg) if msg is not None else "")

            if role == "system" and system_prompt is None:
                system_prompt = content

            tool_calls: list[ToolCall] = []
            for tc_idx, tc in enumerate(step.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                call_id = str(tc.get("tool_call_id") or tc.get("id") or f"step{idx}_tc{tc_idx}")
                fn_name = str(tc.get("function_name") or tc.get("name") or "")
                raw_args = tc.get("arguments")
                parsed_args, parse_err = _parse_arguments(raw_args)
                call_id_to_name[call_id] = fn_name
                tool_calls.append(
                    ToolCall(
                        call_id=call_id,
                        name=fn_name,
                        arguments=parsed_args,
                        turn_index=idx,
                        raw_arguments=raw_args,
                        parse_error=parse_err,
                    )
                )

            tool_results: list[ToolResult] = []
            obs = step.get("observation")
            if isinstance(obs, dict):
                for r_idx, res in enumerate(obs.get("results") or []):
                    if not isinstance(res, dict):
                        continue
                    src_id = str(res.get("source_call_id") or res.get("tool_call_id") or f"step{idx}_res{r_idx}")
                    raw_content = res.get("content")
                    parsed_content = _try_parse_json(raw_content)
                    is_err, err_msg, status_code = _classify_result_error(raw_content, parsed_content)
                    tool_results.append(
                        ToolResult(
                            call_id=src_id,
                            tool_name=call_id_to_name.get(src_id),
                            raw_content=raw_content,
                            parsed_content=parsed_content,
                            turn_index=idx,
                            is_error=is_err,
                            error_message=err_msg,
                            status_code=status_code,
                            extra={k: v for k, v in res.items() if k not in {"source_call_id", "content"}},
                        )
                    )

            step_extra = {
                k: v
                for k, v in step.items()
                if k not in {"step_id", "source", "message", "tool_calls", "observation", "timestamp"}
            }
            turns.append(
                CanonicalTurn(
                    index=idx,
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    step_id=step.get("step_id"),
                    timestamp=step.get("timestamp"),
                    extra=step_extra,
                )
            )

        return CanonicalTrace(
            trace_id=trace_id,
            source_format=self.name,
            schema_version=record.get("schema_version"),
            agent_name=agent.get("name"),
            model_name=agent.get("model_name"),
            agent_version=agent.get("version"),
            system_prompt=system_prompt,
            tool_specs=tool_specs,
            turns=turns,
            outcome=extra.get("outcome") or record.get("outcome"),
            extra=extra,
        )


class AnthropicMessagesAdapter(TraceAdapter):
    """Adapter for Anthropic Messages API trajectories with content blocks."""

    name = "anthropic"

    def can_parse(self, record: dict[str, Any]) -> float:
        msgs = record.get("messages")
        if not isinstance(msgs, list) or not msgs:
            return 0.0
        for m in msgs[:10]:
            if isinstance(m, dict) and isinstance(m.get("content"), list):
                for blk in m["content"]:
                    if isinstance(blk, dict) and blk.get("type") in {"tool_use", "tool_result", "thinking"}:
                        return 0.95
        if "system" in record and "messages" in record and "tools" in record:
            tools = record.get("tools")
            if isinstance(tools, list) and tools and isinstance(tools[0], dict) and "input_schema" in tools[0]:
                return 0.9
        return 0.0

    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        trace_id = str(record.get("id") or record.get("session_id") or record.get("trace_id") or fallback_id)
        tool_specs = parse_tool_specs(record.get("tools"), source="inline:anthropic")
        turns: list[CanonicalTurn] = []
        call_id_to_name: dict[str, str] = {}

        system_raw = record.get("system")
        system_prompt: Optional[str] = None
        if isinstance(system_raw, str):
            system_prompt = system_raw
            turns.append(CanonicalTurn(index=0, role="system", content=system_prompt))
        elif isinstance(system_raw, list):
            texts = [b.get("text", "") for b in system_raw if isinstance(b, dict)]
            system_prompt = "\n".join(t for t in texts if t)
            turns.append(CanonicalTurn(index=0, role="system", content=system_prompt))

        for m in record.get("messages") or []:
            if not isinstance(m, dict):
                continue
            idx = len(turns)
            raw_role = str(m.get("role") or "event").lower()
            role = "agent" if raw_role == "assistant" else raw_role
            raw_content = m.get("content")
            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            tool_results: list[ToolResult] = []

            if isinstance(raw_content, str):
                text_parts.append(raw_content)
            elif isinstance(raw_content, list):
                for blk in raw_content:
                    if not isinstance(blk, dict):
                        continue
                    btype = blk.get("type")
                    if btype == "text":
                        text_parts.append(str(blk.get("text") or ""))
                    elif btype == "tool_use":
                        cid = str(blk.get("id") or f"turn{idx}_tu{len(tool_calls)}")
                        name = str(blk.get("name") or "")
                        parsed_args, parse_err = _parse_arguments(blk.get("input"))
                        call_id_to_name[cid] = name
                        tool_calls.append(
                            ToolCall(
                                call_id=cid,
                                name=name,
                                arguments=parsed_args,
                                turn_index=idx,
                                raw_arguments=blk.get("input"),
                                parse_error=parse_err,
                            )
                        )
                    elif btype == "tool_result":
                        cid = str(blk.get("tool_use_id") or "")
                        rc = blk.get("content")
                        if isinstance(rc, list):
                            rc = "\n".join(
                                str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in rc
                            )
                        pc = _try_parse_json(rc)
                        is_err, err_msg, status_code = _classify_result_error(rc, pc)
                        if blk.get("is_error") is True:
                            is_err = True
                            err_msg = err_msg or str(rc)[:200]
                        tool_results.append(
                            ToolResult(
                                call_id=cid,
                                tool_name=call_id_to_name.get(cid),
                                raw_content=rc,
                                parsed_content=pc,
                                turn_index=idx,
                                is_error=is_err,
                                error_message=err_msg,
                                status_code=status_code,
                            )
                        )

            # If a user turn only carries tool_results, normalize role to tool
            if role == "user" and tool_results and not "".join(text_parts).strip():
                role = "tool"

            turns.append(
                CanonicalTurn(
                    index=idx,
                    role=role,
                    content="\n".join(p for p in text_parts if p),
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                )
            )

        extra = dict(record.get("extra") or record.get("metadata") or {})
        return CanonicalTrace(
            trace_id=trace_id,
            source_format=self.name,
            model_name=record.get("model"),
            system_prompt=system_prompt,
            tool_specs=tool_specs,
            turns=turns,
            outcome=extra.get("outcome") or record.get("outcome"),
            extra=extra,
        )


class OpenAIMessagesAdapter(TraceAdapter):
    """Adapter for OpenAI Chat Completions / Assistants / ShareGPT style traces."""

    name = "openai"

    def can_parse(self, record: dict[str, Any]) -> float:
        msgs = record.get("messages")
        if not isinstance(msgs, list) or not msgs:
            return 0.0
        first = msgs[0]
        if isinstance(first, dict) and "role" in first:
            return 0.85
        return 0.0

    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        trace_id = str(record.get("id") or record.get("session_id") or record.get("trace_id") or fallback_id)
        tool_specs = parse_tool_specs(record.get("tools") or record.get("functions"), source="inline:openai")
        turns: list[CanonicalTurn] = []
        call_id_to_name: dict[str, str] = {}
        system_prompt: Optional[str] = None

        role_map = {
            "system": "system",
            "developer": "system",
            "user": "user",
            "assistant": "agent",
            "tool": "tool",
            "function": "tool",
        }

        for m in record.get("messages") or []:
            if not isinstance(m, dict):
                continue
            idx = len(turns)
            raw_role = str(m.get("role") or "event").lower()
            role = role_map.get(raw_role, raw_role)
            raw_content = m.get("content")
            if isinstance(raw_content, list):
                content = "\n".join(
                    str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in raw_content
                )
            elif raw_content is None:
                content = ""
            else:
                content = str(raw_content)

            if role == "system" and system_prompt is None:
                system_prompt = content

            tool_calls: list[ToolCall] = []
            for tc_idx, tc in enumerate(m.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                cid = str(tc.get("id") or f"turn{idx}_tc{tc_idx}")
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments")
                parsed_args, parse_err = _parse_arguments(raw_args)
                call_id_to_name[cid] = name
                tool_calls.append(
                    ToolCall(
                        call_id=cid,
                        name=name,
                        arguments=parsed_args,
                        turn_index=idx,
                        raw_arguments=raw_args,
                        parse_error=parse_err,
                    )
                )

            if isinstance(m.get("function_call"), dict):
                fc = m["function_call"]
                cid = f"turn{idx}_fc0"
                name = str(fc.get("name") or "")
                raw_args = fc.get("arguments")
                parsed_args, parse_err = _parse_arguments(raw_args)
                call_id_to_name[cid] = name
                tool_calls.append(
                    ToolCall(
                        call_id=cid,
                        name=name,
                        arguments=parsed_args,
                        turn_index=idx,
                        raw_arguments=raw_args,
                        parse_error=parse_err,
                    )
                )

            tool_results: list[ToolResult] = []
            if role == "tool":
                cid = str(m.get("tool_call_id") or "")
                tname = m.get("name") or call_id_to_name.get(cid)
                pc = _try_parse_json(raw_content)
                is_err, err_msg, status_code = _classify_result_error(raw_content, pc)
                tool_results.append(
                    ToolResult(
                        call_id=cid,
                        tool_name=tname,
                        raw_content=raw_content,
                        parsed_content=pc,
                        turn_index=idx,
                        is_error=is_err,
                        error_message=err_msg,
                        status_code=status_code,
                    )
                )

            turns.append(
                CanonicalTurn(
                    index=idx,
                    role=role,
                    content="" if role == "tool" else content,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    timestamp=m.get("timestamp"),
                )
            )

        extra = dict(record.get("extra") or record.get("metadata") or {})
        return CanonicalTrace(
            trace_id=trace_id,
            source_format=self.name,
            model_name=record.get("model"),
            system_prompt=system_prompt,
            tool_specs=tool_specs,
            turns=turns,
            outcome=extra.get("outcome") or record.get("outcome"),
            extra=extra,
        )


class OTelSpanAdapter(TraceAdapter):
    """Adapter for OpenTelemetry / OpenInference / Langfuse span-based agent traces."""

    name = "otel"

    def can_parse(self, record: dict[str, Any]) -> float:
        spans = record.get("spans") or record.get("observations")
        if isinstance(spans, list) and spans and isinstance(spans[0], dict):
            s0 = spans[0]
            if any(k in s0 for k in ("span_id", "spanId", "attributes", "kind", "type")):
                return 0.9
        return 0.0

    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        trace_id = str(record.get("trace_id") or record.get("traceId") or record.get("id") or fallback_id)
        raw_spans = list(record.get("spans") or record.get("observations") or [])
        raw_spans.sort(key=lambda s: str(s.get("start_time") or s.get("startTime") or ""))

        turns: list[CanonicalTurn] = []
        model_name: Optional[str] = record.get("model")
        system_prompt: Optional[str] = None

        for sp in raw_spans:
            if not isinstance(sp, dict):
                continue
            attrs = sp.get("attributes") if isinstance(sp.get("attributes"), dict) else {}
            kind = str(
                attrs.get("openinference.span.kind")
                or attrs.get("gen_ai.operation.name")
                or sp.get("kind")
                or sp.get("type")
                or ""
            ).lower()
            name = str(sp.get("name") or "")
            ts = sp.get("start_time") or sp.get("startTime")
            model_name = model_name or attrs.get("gen_ai.request.model") or attrs.get("llm.model_name")

            if "tool" in kind or "tool.name" in attrs or "gen_ai.tool.name" in attrs:
                idx = len(turns)
                tname = str(attrs.get("gen_ai.tool.name") or attrs.get("tool.name") or name)
                cid = str(sp.get("span_id") or sp.get("spanId") or f"span_{idx}")
                raw_in = attrs.get("input.value") or attrs.get("tool.parameters") or sp.get("input")
                parsed_args, parse_err = _parse_arguments(raw_in)
                raw_out = attrs.get("output.value") or attrs.get("tool.output") or sp.get("output")
                parsed_out = _try_parse_json(raw_out)
                is_err, err_msg, status_code = _classify_result_error(raw_out, parsed_out)
                if str(sp.get("status") or "").lower() == "error":
                    is_err = True
                    err_msg = err_msg or str(sp.get("status_message") or "span error")

                turns.append(
                    CanonicalTurn(
                        index=idx,
                        role="agent",
                        content="",
                        tool_calls=[
                            ToolCall(
                                call_id=cid,
                                name=tname,
                                arguments=parsed_args,
                                turn_index=idx,
                                raw_arguments=raw_in,
                                parse_error=parse_err,
                            )
                        ],
                        tool_results=[
                            ToolResult(
                                call_id=cid,
                                tool_name=tname,
                                raw_content=raw_out,
                                parsed_content=parsed_out,
                                turn_index=idx,
                                is_error=is_err,
                                error_message=err_msg,
                                status_code=status_code,
                            )
                        ],
                        step_id=cid,
                        timestamp=str(ts) if ts is not None else None,
                    )
                )
            else:
                inp = attrs.get("input.value") or attrs.get("gen_ai.prompt") or sp.get("input")
                out = attrs.get("output.value") or attrs.get("gen_ai.completion") or sp.get("output")
                if inp:
                    inp_str = inp if isinstance(inp, str) else json.dumps(inp)
                    if not turns or turns[-1].content != inp_str:
                        turns.append(
                            CanonicalTurn(
                                index=len(turns),
                                role="user",
                                content=inp_str,
                                step_id=sp.get("span_id") or sp.get("spanId"),
                                timestamp=str(ts) if ts is not None else None,
                            )
                        )
                if out:
                    out_str = out if isinstance(out, str) else json.dumps(out)
                    turns.append(
                        CanonicalTurn(
                            index=len(turns),
                            role="agent",
                            content=out_str,
                            step_id=sp.get("span_id") or sp.get("spanId"),
                            timestamp=str(ts) if ts is not None else None,
                        )
                    )

        extra = dict(record.get("extra") or record.get("metadata") or {})
        return CanonicalTrace(
            trace_id=trace_id,
            source_format=self.name,
            model_name=model_name,
            system_prompt=system_prompt,
            turns=turns,
            outcome=extra.get("outcome") or record.get("outcome"),
            extra=extra,
        )


class MappingAdapter(TraceAdapter):
    """Declarative JSON-config adapter for onboarding novel trace formats without Python code."""

    name = "mapping"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.name = str(config.get("name") or "mapping")

    def can_parse(self, record: dict[str, Any]) -> float:
        turns = _extract_dot_path(record, self.config.get("turns_path"))
        return 0.99 if isinstance(turns, list) else 0.0

    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        cfg = self.config
        trace_id = str(_extract_dot_path(record, cfg.get("trace_id_path")) or fallback_id)
        role_map = cfg.get("role_map") or {}
        raw_turns = _extract_dot_path(record, cfg.get("turns_path")) or []
        turns: list[CanonicalTurn] = []
        call_id_to_name: dict[str, str] = {}
        system_prompt: Optional[str] = None

        for idx, item in enumerate(raw_turns):
            if not isinstance(item, dict):
                continue
            raw_role = str(_extract_dot_path(item, cfg.get("role_path")) or "event").lower()
            role = role_map.get(raw_role, raw_role)
            raw_content = _extract_dot_path(item, cfg.get("content_path"))
            content = raw_content if isinstance(raw_content, str) else (json.dumps(raw_content) if raw_content is not None else "")
            if role == "system" and system_prompt is None:
                system_prompt = content

            tool_calls: list[ToolCall] = []
            tc_list = _extract_dot_path(item, cfg.get("tool_calls_path")) or []
            if isinstance(tc_list, dict):
                tc_list = [tc_list]
            for tc_i, tc in enumerate(tc_list):
                if not isinstance(tc, dict):
                    continue
                cid = str(_extract_dot_path(tc, cfg.get("tool_call_id_path")) or f"t{idx}_c{tc_i}")
                name = str(_extract_dot_path(tc, cfg.get("tool_name_path")) or "")
                raw_args = _extract_dot_path(tc, cfg.get("tool_args_path"))
                parsed_args, parse_err = _parse_arguments(raw_args)
                call_id_to_name[cid] = name
                tool_calls.append(
                    ToolCall(
                        call_id=cid,
                        name=name,
                        arguments=parsed_args,
                        turn_index=idx,
                        raw_arguments=raw_args,
                        parse_error=parse_err,
                    )
                )

            tool_results: list[ToolResult] = []
            tr_list = _extract_dot_path(item, cfg.get("tool_results_path")) or []
            if isinstance(tr_list, dict):
                tr_list = [tr_list]
            for tr_i, tr in enumerate(tr_list):
                if not isinstance(tr, dict):
                    continue
                cid = str(_extract_dot_path(tr, cfg.get("tool_result_id_path")) or f"t{idx}_r{tr_i}")
                rc = _extract_dot_path(tr, cfg.get("tool_result_content_path"))
                pc = _try_parse_json(rc)
                is_err, err_msg, status_code = _classify_result_error(rc, pc)
                tool_results.append(
                    ToolResult(
                        call_id=cid,
                        tool_name=call_id_to_name.get(cid),
                        raw_content=rc,
                        parsed_content=pc,
                        turn_index=idx,
                        is_error=is_err,
                        error_message=err_msg,
                        status_code=status_code,
                    )
                )

            turns.append(
                CanonicalTurn(
                    index=idx,
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    timestamp=_extract_dot_path(item, cfg.get("timestamp_path")),
                )
            )

        outcome = _extract_dot_path(record, cfg.get("outcome_path"))
        extra = dict(record.get("extra") or record.get("metadata") or {})
        return CanonicalTrace(
            trace_id=trace_id,
            source_format=self.name,
            agent_name=_extract_dot_path(record, cfg.get("agent_name_path")),
            model_name=_extract_dot_path(record, cfg.get("model_name_path")),
            system_prompt=system_prompt,
            turns=turns,
            outcome=str(outcome) if outcome is not None else None,
            extra=extra,
        )


class GenericFallbackAdapter(TraceAdapter):
    """Best-effort heuristic fallback so novel/unknown formats never crash ingestion."""

    name = "generic"

    TURN_KEYS = ("steps", "messages", "turns", "events", "history", "trajectory", "conversation", "dialog", "log")

    def can_parse(self, record: dict[str, Any]) -> float:
        return 0.1

    def parse(self, record: dict[str, Any], fallback_id: str) -> CanonicalTrace:
        trace_id = str(
            record.get("session_id")
            or record.get("trace_id")
            or record.get("id")
            or record.get("conversation_id")
            or fallback_id
        )
        raw_turns: list[Any] = []
        matched_key: Optional[str] = None
        for k in self.TURN_KEYS:
            if isinstance(record.get(k), list):
                raw_turns = record[k]
                matched_key = k
                break

        turns: list[CanonicalTurn] = []
        for idx, item in enumerate(raw_turns):
            if isinstance(item, dict):
                raw_role = str(item.get("role") or item.get("source") or item.get("speaker") or item.get("actor") or "event").lower()
                role = "agent" if raw_role in {"assistant", "bot", "model", "ai"} else raw_role
                msg = item.get("message") or item.get("content") or item.get("text") or item.get("body") or ""
                content = msg if isinstance(msg, str) else json.dumps(msg)
                turns.append(CanonicalTurn(index=idx, role=role, content=content, extra=item))
            else:
                turns.append(CanonicalTurn(index=idx, role="event", content=str(item)))

        extra = dict(record.get("extra") or {})
        extra["_generic_matched_turns_key"] = matched_key
        extra["_raw_top_keys"] = sorted(record.keys())
        return CanonicalTrace(
            trace_id=trace_id,
            source_format=self.name,
            turns=turns,
            outcome=record.get("outcome") or extra.get("outcome"),
            extra=extra,
        )


class AdapterRegistry:
    """Registry of trace format adapters supporting auto-detection and custom extensions."""

    def __init__(self) -> None:
        self._adapters: list[TraceAdapter] = [
            ATIFAdapter(),
            AnthropicMessagesAdapter(),
            OpenAIMessagesAdapter(),
            OTelSpanAdapter(),
            GenericFallbackAdapter(),
        ]

    def register(self, adapter: TraceAdapter, priority_first: bool = True) -> None:
        if priority_first:
            self._adapters.insert(0, adapter)
        else:
            self._adapters.append(adapter)

    def get(self, name: str) -> TraceAdapter:
        for a in self._adapters:
            if a.name == name:
                return a
        raise ValueError(f"Unknown trace adapter: {name!r}. Available: {[a.name for a in self._adapters]}")

    def detect(self, record: dict[str, Any]) -> TraceAdapter:
        best_adapter = self._adapters[-1]
        best_score = -1.0
        for adapter in self._adapters:
            score = adapter.can_parse(record)
            if score > best_score:
                best_score = score
                best_adapter = adapter
        return best_adapter


DEFAULT_REGISTRY = AdapterRegistry()


def _iter_raw_records_from_file(path: Path) -> Iterator[tuple[dict[str, Any], Optional[int]]]:
    """Stream raw dict records from .jsonl, .json, .jsonl.gz, .json.gz files."""
    is_gz = path.suffix == ".gz"
    opener = gzip.open if is_gz else open
    stem_suffix = Path(path.stem).suffix if is_gz else path.suffix

    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[call-overload]
        if stem_suffix in {".jsonl", ".ndjson"}:
            for line_no, line in enumerate(f, start=1):
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if isinstance(obj, dict):
                    yield obj, line_no
        else:
            data = json.load(f)
            if isinstance(data, list):
                for idx, obj in enumerate(data, start=1):
                    if isinstance(obj, dict):
                        yield obj, idx
            elif isinstance(data, dict):
                # Support wrapper containers like {"traces": [...]}
                for wrapper_key in ("traces", "sessions", "trajectories", "data", "items"):
                    if isinstance(data.get(wrapper_key), list) and data[wrapper_key] and isinstance(data[wrapper_key][0], dict):
                        for idx, obj in enumerate(data[wrapper_key], start=1):
                            yield obj, idx
                        return
                yield data, 1


def _expand_input_paths(inputs: list[str | Path]) -> list[Path]:
    paths: list[Path] = []
    valid_exts = {".jsonl", ".ndjson", ".json", ".gz"}
    for raw in inputs:
        if str(raw) == "-":
            paths.append(Path("-"))
            continue
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix in valid_exts:
                    paths.append(child)
        elif p.exists():
            paths.append(p)
        else:
            raise FileNotFoundError(f"Trace input not found: {p}")
    return paths


def iter_traces(
    inputs: str | Path | list[str | Path],
    format_name: str = "auto",
    tool_schema_path: Optional[str | Path] = None,
    mapping_config_path: Optional[str | Path] = None,
    registry: Optional[AdapterRegistry] = None,
) -> Iterator[CanonicalTrace]:
    """Stream CanonicalTrace objects across one or more files, directories, or stdin ('-')."""
    reg = registry or AdapterRegistry()
    if mapping_config_path is not None:
        with Path(mapping_config_path).open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        reg.register(MappingAdapter(cfg), priority_first=True)
        if format_name == "auto":
            format_name = str(cfg.get("name") or "mapping")

    external_specs: dict[str, ToolSpec] = {}
    if tool_schema_path is not None:
        external_specs = load_tool_schema_file(tool_schema_path)

    input_list = [inputs] if isinstance(inputs, (str, Path)) else list(inputs)
    expanded = _expand_input_paths(input_list)

    counter = 0
    for path in expanded:
        if str(path) == "-":
            stream_iter: Iterator[tuple[dict[str, Any], Optional[int]]] = (
                (json.loads(line), i)
                for i, line in enumerate(sys.stdin, start=1)
                if line.strip()
            )
            src_label = "<stdin>"
        else:
            stream_iter = _iter_raw_records_from_file(path)
            src_label = str(path)

        for record, line_no in stream_iter:
            counter += 1
            adapter = reg.detect(record) if format_name == "auto" else reg.get(format_name)
            trace = adapter.parse(record, fallback_id=f"trace_{counter:04d}")
            trace.source_file = src_label
            trace.source_line = line_no
            if external_specs:
                merged = dict(trace.tool_specs)
                merged.update(external_specs)
                trace.tool_specs = merged
            yield trace


def load_traces(
    inputs: str | Path | list[str | Path],
    format_name: str = "auto",
    tool_schema_path: Optional[str | Path] = None,
    mapping_config_path: Optional[str | Path] = None,
    registry: Optional[AdapterRegistry] = None,
) -> list[CanonicalTrace]:
    """Convenience wrapper to materialize traces into a list."""
    return list(
        iter_traces(
            inputs=inputs,
            format_name=format_name,
            tool_schema_path=tool_schema_path,
            mapping_config_path=mapping_config_path,
            registry=registry,
        )
    )
