#!/usr/bin/env python3
"""Read-only Agentic OS memory adapter skeleton.

This is the Phase 2.1 fixture-backed contract surface from ADR-0009. It does
not connect to Cognee and it intentionally does not expose write tools.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any


CONTRACT_NAME = "agentic-os-memory"
CONTRACT_VERSION = "0.1.0"
MCP_PROTOCOL_TARGET = "2025-06-18"

READ_TOOL_NAMES = [
    "memory.search",
    "memory.get",
    "memory.list_entities",
    "memory.timeline",
    "memory.graph_neighbors",
]

MEMORY_TYPES = {
    "semantic_fact",
    "short_term_summary",
    "persona",
    "episodic_event",
    "entity",
    "repo_chunk",
}

ENTITY_TYPES = {"task", "adr", "agent", "person", "file", "branch", "pr", "commit"}
PUBLIC_NAMESPACES = {"shared", "system/derived"}
RETRYABLE_ERRORS = {"BACKEND_UNAVAILABLE"}


class MemoryToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def success(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "structuredContent": payload,
    }


def error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "code": code,
        "message": message,
        "details": details or {},
        "retryable": code in RETRYABLE_ERRORS,
    }
    return {
        "isError": True,
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
        "structuredContent": payload,
    }


def parse_iso8601(value: str, field: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryToolError("INVALID_ARGUMENT", f"{field} must be an ISO-8601 timestamp", {"field": field}) from exc
    return value


def require_string(args: dict[str, Any], field: str) -> str:
    value = args.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MemoryToolError("INVALID_ARGUMENT", f"{field} is required", {"field": field})
    return value.strip()


def bounded_int(args: dict[str, Any], field: str, default: int, minimum: int, maximum: int) -> int:
    value = args.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise MemoryToolError(
            "INVALID_ARGUMENT",
            f"{field} must be between {minimum} and {maximum}",
            {"field": field, "minimum": minimum, "maximum": maximum},
        )
    return value


def canonical_ref(record: dict[str, Any]) -> str:
    return str(record.get("canonical_id") or record.get("id") or "")


def is_entity_match(record: dict[str, Any], entity_id: str) -> bool:
    return entity_id in {
        str(record.get("id", "")),
        str(record.get("canonical_id", "")),
        str(record.get("name", "")),
    }


class FixtureMemoryBackend:
    """Tiny in-memory backend used by T-0022 tests and smoke runs."""

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> None:
        self.records = records or []
        self.events = events or []
        self.edges = edges or []

    @classmethod
    def with_records(
        cls,
        records: list[dict[str, Any]],
        events: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> "FixtureMemoryBackend":
        return cls(records=records, events=events, edges=edges)

    def search(
        self,
        query: str,
        namespaces: list[str],
        memory_type: str | None,
        refs: dict[str, list[str]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for record in self.records:
            if record.get("status", "active") != "active":
                continue
            if record.get("namespace") not in namespaces:
                continue
            if memory_type and record.get("type") != memory_type:
                continue
            if refs and not self._record_matches_refs(record, refs):
                continue

            haystack = " ".join(
                str(record.get(key, "")) for key in ("id", "content", "name", "canonical_id", "entity_type")
            ).lower()
            if query_lower not in haystack:
                continue

            item = dict(record)
            item["score"] = 1.0
            results.append(item)
        return results[:top_k]

    def get(self, record_id: str) -> dict[str, Any] | None:
        for record in self.records:
            if record.get("id") == record_id:
                return dict(record)
        return None

    def list_entities(self, entity_type: str | None, query: str | None, limit: int) -> list[dict[str, Any]]:
        query_lower = query.lower() if query else None
        entities: list[dict[str, Any]] = []
        for record in self.records:
            if record.get("type") != "entity":
                continue
            if entity_type and record.get("entity_type") != entity_type:
                continue
            if query_lower:
                haystack = " ".join(str(record.get(key, "")) for key in ("canonical_id", "name", "content")).lower()
                if query_lower not in haystack:
                    continue
            entities.append(
                {
                    "id": record.get("id"),
                    "entity_type": record.get("entity_type"),
                    "canonical_id": record.get("canonical_id"),
                    "name": record.get("name") or record.get("content"),
                    "aliases": record.get("aliases", []),
                    "relations": record.get("relations", []),
                }
            )
        return entities[:limit]

    def entity_exists(self, entity_id: str) -> bool:
        return any(record.get("type") == "entity" and is_entity_match(record, entity_id) for record in self.records)

    def timeline(
        self,
        entity_id: str,
        event_types: list[str],
        since: str | None,
        until: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for event_record in self.events:
            if entity_id not in set(event_record.get("entity_ids", [])) | {str(event_record.get("task_id", ""))}:
                continue
            if event_types and event_record.get("event_type") not in event_types:
                continue
            occurred = str(event_record.get("occurred_at", ""))
            if since and occurred < since:
                continue
            if until and occurred > until:
                continue
            events.append({key: value for key, value in event_record.items() if key != "entity_ids"})
        return events[:limit]

    def graph_neighbors(
        self,
        start_id: str,
        depth: int,
        relation_types: list[str],
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        frontier = {start_id}
        visited = {start_id}
        selected_edges: list[dict[str, Any]] = []
        for _ in range(depth):
            next_frontier: set[str] = set()
            for edge in self.edges:
                if relation_types and edge.get("type") not in relation_types:
                    continue
                if edge.get("from") in frontier or edge.get("to") in frontier:
                    selected_edges.append(dict(edge))
                    next_frontier.add(str(edge.get("from")))
                    next_frontier.add(str(edge.get("to")))
            frontier = next_frontier - visited
            visited.update(next_frontier)
            if len(selected_edges) >= limit:
                break

        node_ids = sorted(visited - {start_id})[:limit]
        nodes = [self._node_for(node_id) for node_id in node_ids]
        return nodes, selected_edges[:limit]

    def _node_for(self, node_id: str) -> dict[str, Any]:
        record = self.get(node_id)
        if record:
            return {"id": node_id, "type": record.get("type"), "label": record.get("name") or record.get("content")}
        return {"id": node_id, "type": "unknown", "label": node_id}

    def _record_matches_refs(self, record: dict[str, Any], refs: dict[str, list[str]]) -> bool:
        record_refs = record.get("refs", {})
        for key, expected_values in refs.items():
            if not expected_values:
                continue
            actual_values = set(record_refs.get(key, []))
            if not actual_values.intersection(expected_values):
                return False
        return True


class MemoryAdapter:
    def __init__(self, backend: FixtureMemoryBackend) -> None:
        self.backend = backend

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memory.search",
                "description": "Search shared and derived Agentic OS memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "type": {"type": ["string", "null"]},
                        "namespaces": {"type": "array", "items": {"type": "string"}},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                        "include_private": {"type": "boolean"},
                        "refs": {"type": "object"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memory.get",
                "description": "Fetch one memory record by id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "include_neighbors": {"type": "boolean"}},
                    "required": ["id"],
                },
            },
            {
                "name": "memory.list_entities",
                "description": "Browse canonical memory entity records.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_type": {"type": ["string", "null"]},
                        "query": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 250},
                        "cursor": {"type": ["string", "null"]},
                    },
                },
            },
            {
                "name": "memory.timeline",
                "description": "Return episodic records for an entity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "since": {"type": ["string", "null"]},
                        "until": {"type": ["string", "null"]},
                        "event_types": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 250},
                        "cursor": {"type": ["string", "null"]},
                    },
                    "required": ["entity_id"],
                },
            },
            {
                "name": "memory.graph_neighbors",
                "description": "Traverse graph relationships from a memory record or entity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "depth": {"type": "integer", "minimum": 1, "maximum": 2},
                        "relation_types": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 250},
                    },
                    "required": ["id"],
                },
            },
        ]

    def call_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        identity: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        args = args or {}
        identity = identity or {"agent_id": "codex", "role": "reader"}
        try:
            if name == "memory.search":
                return success(self.memory_search(args, identity))
            if name == "memory.get":
                return success(self.memory_get(args, identity))
            if name == "memory.list_entities":
                return success(self.memory_list_entities(args))
            if name == "memory.timeline":
                return success(self.memory_timeline(args))
            if name == "memory.graph_neighbors":
                return success(self.memory_graph_neighbors(args))
            raise MemoryToolError("INVALID_ARGUMENT", f"unknown tool: {name}", {"tool": name})
        except MemoryToolError as exc:
            return error(exc.code, exc.message, exc.details)

    def memory_search(self, args: dict[str, Any], identity: dict[str, str]) -> dict[str, Any]:
        query = require_string(args, "query")
        memory_type = args.get("type")
        if memory_type is not None and memory_type not in MEMORY_TYPES:
            raise MemoryToolError("INVALID_ARGUMENT", "type is invalid", {"field": "type"})
        top_k = bounded_int(args, "top_k", 10, 1, 50)
        refs = args.get("refs") or {}
        if not isinstance(refs, dict):
            raise MemoryToolError("INVALID_ARGUMENT", "refs must be an object", {"field": "refs"})

        namespaces = args.get("namespaces") or ["shared", "system/derived"]
        include_private = bool(args.get("include_private", False))
        namespaces = self._validate_namespaces(namespaces, include_private, identity)

        return {
            "contract_version": CONTRACT_VERSION,
            "results": self.backend.search(query, namespaces, memory_type, refs, top_k),
            "next_cursor": None,
        }

    def memory_get(self, args: dict[str, Any], identity: dict[str, str]) -> dict[str, Any]:
        record_id = require_string(args, "id")
        record = self.backend.get(record_id)
        if not record:
            raise MemoryToolError("NOT_FOUND", f"memory record not found: {record_id}", {"id": record_id})
        self._validate_namespaces([str(record.get("namespace", ""))], False, identity)
        neighbors: list[dict[str, Any]] = []
        if args.get("include_neighbors", False):
            nodes, edges = self.backend.graph_neighbors(record_id, 1, [], 100)
            neighbors = [{"nodes": nodes, "edges": edges}]
        return {"contract_version": CONTRACT_VERSION, "record": record, "neighbors": neighbors}

    def memory_list_entities(self, args: dict[str, Any]) -> dict[str, Any]:
        entity_type = args.get("entity_type")
        if entity_type is not None and entity_type not in ENTITY_TYPES:
            raise MemoryToolError("INVALID_ARGUMENT", "entity_type is invalid", {"field": "entity_type"})
        query = args.get("query")
        if query is not None and not isinstance(query, str):
            raise MemoryToolError("INVALID_ARGUMENT", "query must be a string", {"field": "query"})
        limit = bounded_int(args, "limit", 50, 1, 250)
        return {
            "contract_version": CONTRACT_VERSION,
            "entities": self.backend.list_entities(entity_type, query, limit),
            "next_cursor": None,
        }

    def memory_timeline(self, args: dict[str, Any]) -> dict[str, Any]:
        entity_id = require_string(args, "entity_id")
        if not self.backend.entity_exists(entity_id) and not any(
            entity_id in set(event.get("entity_ids", [])) | {str(event.get("task_id", ""))} for event in self.backend.events
        ):
            raise MemoryToolError("NOT_FOUND", f"entity not found: {entity_id}", {"entity_id": entity_id})
        since = args.get("since")
        until = args.get("until")
        if since is not None:
            since = parse_iso8601(str(since), "since")
        if until is not None:
            until = parse_iso8601(str(until), "until")
        event_types = args.get("event_types") or []
        if not isinstance(event_types, list) or not all(isinstance(item, str) for item in event_types):
            raise MemoryToolError("INVALID_ARGUMENT", "event_types must be a list of strings", {"field": "event_types"})
        limit = bounded_int(args, "limit", 100, 1, 250)
        return {
            "contract_version": CONTRACT_VERSION,
            "events": self.backend.timeline(entity_id, event_types, since, until, limit),
            "next_cursor": None,
        }

    def memory_graph_neighbors(self, args: dict[str, Any]) -> dict[str, Any]:
        start_id = require_string(args, "id")
        depth = bounded_int(args, "depth", 1, 1, 2)
        limit = bounded_int(args, "limit", 100, 1, 250)
        relation_types = args.get("relation_types") or []
        if not isinstance(relation_types, list) or not all(isinstance(item, str) for item in relation_types):
            raise MemoryToolError(
                "INVALID_ARGUMENT", "relation_types must be a list of strings", {"field": "relation_types"}
            )
        nodes, edges = self.backend.graph_neighbors(start_id, depth, relation_types, limit)
        if not nodes and not edges and not self.backend.get(start_id):
            raise MemoryToolError("NOT_FOUND", f"graph start not found: {start_id}", {"id": start_id})
        return {"contract_version": CONTRACT_VERSION, "start": start_id, "nodes": nodes, "edges": edges}

    def _validate_namespaces(
        self,
        namespaces: Any,
        include_private: bool,
        identity: dict[str, str],
    ) -> list[str]:
        if not isinstance(namespaces, list) or not namespaces or not all(isinstance(item, str) for item in namespaces):
            raise MemoryToolError("INVALID_ARGUMENT", "namespaces must be a non-empty list", {"field": "namespaces"})
        agent_namespace = f"agent/{identity.get('agent_id', '')}"
        allowed = set(PUBLIC_NAMESPACES)
        if include_private:
            allowed.add(agent_namespace)
        forbidden = [namespace for namespace in namespaces if namespace not in allowed]
        if forbidden:
            raise MemoryToolError("FORBIDDEN_NAMESPACE", "caller cannot read requested namespace", {"namespaces": forbidden})
        return namespaces


def adapter_payload(adapter: MemoryAdapter) -> dict[str, Any]:
    return {
        "contract_name": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "mcp_protocol_target": MCP_PROTOCOL_TARGET,
        "tools": adapter.list_tools(),
    }


def handle_jsonrpc(adapter: MemoryAdapter, request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {
            "protocolVersion": MCP_PROTOCOL_TARGET,
            "serverInfo": {"name": CONTRACT_NAME, "version": CONTRACT_VERSION},
            "capabilities": {"tools": {}},
        }
    elif method == "tools/list":
        result = {"tools": adapter.list_tools()}
    elif method == "tools/call":
        result = adapter.call_tool(params.get("name", ""), params.get("arguments") or {})
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve_stdio(adapter: MemoryAdapter) -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle_jsonrpc(adapter, request)
        except Exception as exc:  # pragma: no cover - defensive stdio boundary.
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response, separators=(",", ":")), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agentic OS read-only memory MCP adapter.")
    parser.add_argument("--list-tools", action="store_true", help="Print the read-only tool manifest as JSON.")
    parser.add_argument("--call-tool", help="Call one tool once and print the MCP tool result as JSON.")
    parser.add_argument("--arguments", default="{}", help="JSON object for --call-tool.")
    args = parser.parse_args(argv)

    adapter = MemoryAdapter(FixtureMemoryBackend())
    if args.list_tools:
        print(json.dumps(adapter_payload(adapter), indent=2, sort_keys=True))
        return 0
    if args.call_tool:
        try:
            arguments = json.loads(args.arguments)
        except json.JSONDecodeError as exc:
            print(f"invalid --arguments JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(arguments, dict):
            print("--arguments must decode to a JSON object", file=sys.stderr)
            return 2
        print(json.dumps(adapter.call_tool(args.call_tool, arguments), indent=2, sort_keys=True))
        return 0
    return serve_stdio(adapter)


if __name__ == "__main__":
    raise SystemExit(main())
