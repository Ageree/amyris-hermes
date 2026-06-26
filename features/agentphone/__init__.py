"""AgentPhone integration for Eve — "call a place / book a table".

Public surface:
  client: get_usage, list_agents, list_voices, create_agent, get_agent,
          delete_agent, place_call, load_key, AgentPhoneError
  reservation: book_table (high-level, dry_run by default), build_reservation_prompt
"""
from .client import (
    AgentPhoneError,
    create_agent,
    delete_agent,
    get_agent,
    get_usage,
    list_agents,
    list_voices,
    load_key,
    place_call,
)
from .reservation import book_table, build_reservation_prompt

__all__ = [
    "AgentPhoneError",
    "create_agent",
    "delete_agent",
    "get_agent",
    "get_usage",
    "list_agents",
    "list_voices",
    "load_key",
    "place_call",
    "book_table",
    "build_reservation_prompt",
]
