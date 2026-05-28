#!/usr/bin/env python3
"""
Search filter experiment — Bob's Tech Shop.

Sends a series of test queries to the agent and logs every event in full,
so we can see exactly what MCP tool calls are made, with what parameters,
and what the Shopify MCP returns.

Run with:
  venv/bin/python search_experiment.py
"""

import os
import json
import time
from dotenv import load_dotenv

load_dotenv()

import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN")
AGENT_ID = os.getenv("AGENT_ID")
ENVIRONMENT_ID = os.getenv("ENVIRONMENT_ID")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── Test matrix ──────────────────────────────────────────────────────────────
# Each tuple: (label, message sent to agent)
# Goal: find the boundary between "too broad → 250 slow results" and
#       "too narrow → 0 results", and understand the MCP call that produces each.
TESTS = [
    # Baseline — what does 'no keyword' produce?
    ("all_products",    "Show me everything in the store"),
    # Common keyword searches that currently break
    ("keyword_laptop",  "Show me laptops"),
    ("keyword_gaming",  "What gaming products do you have?"),
    ("keyword_audio",   "I'm looking for headphones or speakers"),
    # Price-scoped searches
    ("price_under_500", "Show me products under $500"),
    # Category + keyword combo
    ("category_cable",  "Do you have any cables or adapters?"),
    # Very broad single word
    ("single_word",     "tech"),
]


def _event_to_dict(event) -> dict:
    """Best-effort serialisation of an SDK event object."""
    try:
        # Most SDK objects expose __dict__; filter out private attrs and None values
        d = {k: v for k, v in vars(event).items() if not k.startswith("_") and v is not None}
        # Nested objects (e.g. content blocks) may not be JSON-serialisable
        return json.loads(json.dumps(d, default=str))
    except Exception:
        return {"__repr__": str(event)[:500]}


def run_test(label: str, query: str) -> dict:
    """Create a fresh session, send one query, capture every event."""
    print(f"\n{'='*64}")
    print(f"TEST: {label}")
    print(f"  → \"{query}\"")
    print("="*64)

    session = client.beta.sessions.create(
        agent=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        title=f"exp:{label}",
    )
    session_id = session.id
    print(f"  session: {session_id}")

    captured: list[dict] = []

    with client.beta.sessions.events.stream(session_id) as stream:
        client.beta.sessions.events.send(
            session_id,
            events=[{
                "type": "user.message",
                "content": [{"type": "text", "text": query}],
            }]
        )

        for event in stream:
            etype = getattr(event, "type", "unknown")
            edata = _event_to_dict(event)
            captured.append({"type": etype, "data": edata})

            if etype == "agent.tool_use":
                name = edata.get("name", "?")
                inp  = edata.get("input", {})
                print(f"\n  [TOOL CALL]  {name}")
                print(f"  input: {json.dumps(inp, indent=4)}")

            elif etype == "agent.tool_result":
                content = edata.get("content", "")
                preview = str(content)[:600]
                print(f"\n  [TOOL RESULT] (first 600 chars)")
                print(f"  {preview}")

            elif etype == "agent.message":
                for block in edata.get("content", []):
                    text = block.get("text", "") if isinstance(block, dict) else str(block)
                    print(f"\n  [AGENT] {text[:400]}")

            elif etype == "session.status_idle":
                print(f"\n  [DONE]")
                break

            else:
                print(f"  [{etype}]")

    return {"label": label, "query": query, "session_id": session_id, "events": captured}


def summarise(results: list[dict]) -> None:
    print(f"\n\n{'='*64}")
    print("EXPERIMENT SUMMARY")
    print("="*64)
    print(f"{'LABEL':<20} {'TOOL CALLS':<12} {'TOOL':<35} INPUT PARAMS")
    print("-"*64)

    for r in results:
        tool_events = [e for e in r["events"] if e["type"] == "agent.tool_use"]
        if not tool_events:
            print(f"{r['label']:<20} {'0':<12} {'(no tool calls)'}")
            continue
        for i, e in enumerate(tool_events):
            name = e["data"].get("name", "?")
            inp  = e["data"].get("input", {})
            label_col = r["label"] if i == 0 else ""
            count_col = str(len(tool_events)) if i == 0 else ""
            inp_str = json.dumps(inp)[:60]
            print(f"{label_col:<20} {count_col:<12} {name:<35} {inp_str}")

    print()


def main():
    if not AGENT_ID:
        print("ERROR: AGENT_ID not in .env — start the backend once to create the agent, then run this script.")
        return
    if not ENVIRONMENT_ID:
        print("ERROR: ENVIRONMENT_ID not in .env — same as above.")
        return

    print(f"Agent:       {AGENT_ID}")
    print(f"Environment: {ENVIRONMENT_ID}")
    print(f"Store:       {SHOPIFY_STORE_DOMAIN}")
    print(f"Running {len(TESTS)} tests...")

    results = []
    for label, query in TESTS:
        result = run_test(label, query)
        results.append(result)
        time.sleep(1)   # brief pause between sessions

    summarise(results)

    # Dump full event log to JSON for offline analysis
    log_path = os.path.join(os.path.dirname(__file__), "search_experiment_log.json")
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Full event log saved to: {log_path}")


if __name__ == "__main__":
    main()
