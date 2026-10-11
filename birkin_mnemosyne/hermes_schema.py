"""Fresh JSON schemas for the standalone Hermes memory-provider tools."""

from __future__ import annotations

from .handoff_transcript import JsonValue as Json


def tool_schemas() -> list[dict[str, Json]]:
    title: dict[str, Json] = {"type": "string", "minLength": 1, "maxLength": 200}
    return [
        {
            "name": "birkin_memory_remember",
            "description": "Create a durable local note without overwriting an existing title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": title,
                    "body": {"type": "string", "minLength": 1, "maxLength": 50000},
                },
                "required": ["title", "body"],
                "additionalProperties": False,
            },
        },
        {
            "name": "birkin_memory_search",
            "description": "Recall local notes by multilingual lexical keywords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "birkin_memory_index",
            "description": "Read the complete resident INDEX or expand one complete topic.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": ["string", "null"]}},
                "additionalProperties": False,
            },
        },
        {
            "name": "birkin_memory_get_note",
            "description": "Read a local note by title/slug or an exact registered INDEX path.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "minLength": 1}},
                "required": ["title"],
                "additionalProperties": False,
            },
        },
    ]
