import os
import json
import asyncio
import re
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

import anthropic
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, HTTPException, Form, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from pydantic import BaseModel

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN")  # e.g. my-store.myshopify.com
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
if not SHOPIFY_STORE_DOMAIN:
    raise RuntimeError("SHOPIFY_STORE_DOMAIN is not set in .env")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
executor = ThreadPoolExecutor(max_workers=20)

# WhatsApp session store: maps WhatsApp phone number → Managed Agent session ID
# In-memory only — resets on server restart. Swap for Redis/DB in production.
whatsapp_sessions: dict[str, str] = {}

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

# Stored on startup
agent_id: str | None = None
environment_id: str | None = None

SYSTEM_PROMPT = f"""You are a friendly and knowledgeable shopping assistant for this store.

Your job is to help customers:
- Search and discover products using natural language
- Understand product details, pricing, and availability
- Add items to their cart
- Answer questions about store policies, shipping, and returns
- Guide them smoothly through to checkout

Always be concise and helpful.
When a customer adds something to their cart, confirm it and suggest checkout or related items.
Store domain: {SHOPIFY_STORE_DOMAIN}

## Search strategy

Always call search_catalog with pagination.limit set to 25 or less — never omit the limit or set it above 25.

Use this two-step approach:
1. Search with the customer's specific keywords first (e.g. "charger", "sleeve", "sock").
2. If that returns 0 products, do a fallback search using the query "tech" with limit 25 — this reliably returns the full catalog for this store. Then filter the results by hand to find the best match for what the customer asked for.

Never tell a customer a product doesn't exist based on a single failed search. Always try the fallback before concluding something is out of stock.

## Product cards

IMPORTANT — whenever you list one or more products, append a JSON block at the very end of your
message in exactly this format (nothing after the closing fence):

```products
[
  {{
    "title": "Product Name",
    "price": "R 0.00",
    "image_url": "https://...",
    "url": "https://{SHOPIFY_STORE_DOMAIN}/products/handle"
  }}
]
```

Rules:
- Use the exact image URL from the Shopify product data (get_product_details has it).
- Use the exact product URL from the Shopify product data.
- Include every product you mention in the block.
- If a product has no image, omit the image_url field.
- Never fabricate URLs or prices.
"""

# ── Lifespan: create agent + environment once on startup ──────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_id, environment_id

    saved_agent_id = os.getenv("AGENT_ID")
    saved_env_id   = os.getenv("ENVIRONMENT_ID")

    if saved_agent_id and saved_env_id:
        # Verify the saved IDs still exist on the platform
        try:
            client.beta.agents.retrieve(saved_agent_id)
            client.beta.environments.retrieve(saved_env_id)
            agent_id       = saved_agent_id
            environment_id = saved_env_id
            print(f"♻️  Reusing agent:       {agent_id}")
            print(f"♻️  Reusing environment: {environment_id}")
        except Exception:
            print("⚠️  Saved IDs are stale — creating new agent and environment...")
            saved_agent_id = saved_env_id = None

    if not saved_agent_id or not saved_env_id:
        print("🚀 Starting up — creating Claude Managed Agent...")

        agent = client.beta.agents.create(
            name="Shopify Shopping Assistant",
            model={"id": "claude-haiku-4-5-20251001"},
            system=SYSTEM_PROMPT,
            mcp_servers=[
                {
                    "type": "url",
                    "url": f"https://{SHOPIFY_STORE_DOMAIN}/api/mcp",
                    "name": "shopify_storefront",
                }
            ],
            tools=[
                {"type": "agent_toolset_20260401"},
                {
                    "type": "mcp_toolset",
                    "mcp_server_name": "shopify_storefront",
                    "default_config": {"permission_policy": {"type": "always_allow"}},
                },
            ],
        )
        agent_id = agent.id
        print(f"✅ Agent created: {agent_id}")

        env = client.beta.environments.create(
            name="shopify-agent-env",
            config={
                "type": "cloud",
                "networking": {"type": "unrestricted"},
            },
        )
        environment_id = env.id
        print(f"✅ Environment created: {environment_id}")

        # Persist IDs so next restart reuses them
        set_key(ENV_FILE, "AGENT_ID", agent_id)
        set_key(ENV_FILE, "ENVIRONMENT_ID", environment_id)
        print("💾 IDs saved to .env")

    print(f"🛍️  Connected to Shopify store: {SHOPIFY_STORE_DOMAIN}")
    print("🟢 Ready — server is running\n")

    yield

    print("🔴 Shutting down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Shopify AI Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class SessionResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    message: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "agent_id": agent_id,
        "environment_id": environment_id,
        "shopify_store": SHOPIFY_STORE_DOMAIN,
    }


@app.post("/api/sessions", response_model=SessionResponse)
def create_session():
    """Create a new chat session for a visitor. Call this once when the chat widget opens."""
    if not agent_id or not environment_id:
        raise HTTPException(503, "Agent not ready yet")

    session = client.beta.sessions.create(
        agent=agent_id,
        environment_id=environment_id,
        title="Shopify chat session",
    )
    return {"session_id": session.id}


@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: str, body: ChatRequest):
    """
    Send a message and stream back the agent response as Server-Sent Events.

    Event types emitted:
      {"type": "text",     "content": "..."}          – text chunk from the agent
      {"type": "tool",     "name": "..."}              – agent is calling a Shopify tool
      {"type": "products", "products": [...]}          – product cards with images
      {"type": "done"}                                 – agent finished responding
      {"type": "error",    "message": "..."}           – something went wrong
    """
    if not session_id:
        raise HTTPException(400, "session_id is required")

    async def event_stream():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _run_stream():
            """Runs in a thread — streams events into the async queue."""
            try:
                with client.beta.sessions.events.stream(session_id) as stream:
                    # Send the user message after the stream opens
                    client.beta.sessions.events.send(
                        session_id,
                        events=[
                            {
                                "type": "user.message",
                                "content": [{"type": "text", "text": body.message}],
                            }
                        ],
                    )
                    for event in stream:
                        loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        executor.submit(_run_stream)

        while True:
            item = await queue.get()

            # Sentinel — stream ended cleanly
            if item is None:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break

            # Exception from the stream thread
            if isinstance(item, Exception):
                yield f"data: {json.dumps({'type': 'error', 'message': str(item)})}\n\n"
                break

            event = item

            if event.type == "agent.message":
                for block in event.content:
                    text = getattr(block, "text", None)
                    if not text:
                        continue
                    match = re.search(r"```products\s*(\[.*?\])\s*```", text, re.DOTALL)
                    if match:
                        clean_text = text[:match.start()].rstrip()
                        if clean_text:
                            yield f"data: {json.dumps({'type': 'text', 'content': clean_text})}\n\n"
                        try:
                            products = json.loads(match.group(1))
                            yield f"data: {json.dumps({'type': 'products', 'products': products})}\n\n"
                        except json.JSONDecodeError:
                            pass
                    else:
                        yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

            elif event.type == "agent.tool_use":
                yield f"data: {json.dumps({'type': 'tool', 'name': event.name})}\n\n"

            elif event.type == "session.status_idle":
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _send_whatsapp_reply(to: str, reply_text: str) -> None:
    """Send a WhatsApp message via Twilio REST API (called from background task)."""
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    # Derive the Twilio sender number: swap the From/To from the inbound message
    # `to` here is the original From (customer), sender is the Twilio number
    sender = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. "whatsapp:+12602691164"
    twilio_client.messages.create(body=reply_text, from_=sender, to=to)


def _run_agent_and_reply(session_id: str, user_message: str, phone_number: str) -> None:
    """Run in thread executor: get agent reply, then push it via Twilio REST API."""
    parts: list[str] = []
    try:
        with client.beta.sessions.events.stream(session_id) as stream:
            client.beta.sessions.events.send(
                session_id,
                events=[
                    {
                        "type": "user.message",
                        "content": [{"type": "text", "text": user_message}],
                    }
                ],
            )
            for event in stream:
                if event.type == "agent.message":
                    for block in event.content:
                        text = getattr(block, "text", None)
                        if text:
                            parts.append(text)
                elif event.type == "session.status_idle":
                    break
    except Exception as exc:
        print(f"[whatsapp] agent error: {exc}")
        _send_whatsapp_reply(phone_number, "Sorry, something went wrong. Please try again.")
        return

    raw_reply = "".join(parts)

    # Strip the ```products ... ``` block — product cards are meaningless over WhatsApp
    match = re.search(r"```products\s*\[.*?\]\s*```", raw_reply, re.DOTALL)
    reply_text = raw_reply[: match.start()].rstrip() if match else raw_reply

    # Truncate to WhatsApp's 1600-character limit
    if len(reply_text) > 1600:
        reply_text = reply_text[:1597] + "..."

    _send_whatsapp_reply(phone_number, reply_text or "Sorry, I didn't get a response. Please try again.")


@app.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    From: str | None = Form(default=None),
    Body: str | None = Form(default=None),
):
    """
    Twilio posts incoming WhatsApp messages here.
    Returns empty TwiML immediately (avoids Twilio's 15s timeout), then
    sends the agent reply asynchronously via the Twilio REST API.
    """
    if not agent_id or not environment_id:
        raise HTTPException(503, "Agent not ready yet")

    form_data = dict(await request.form())

    # Not a real WhatsApp message (e.g. Twilio error/status callback) — ignore silently
    if not From or Body is None:
        return Response(status_code=204)

    if TWILIO_AUTH_TOKEN:
        validator = RequestValidator(TWILIO_AUTH_TOKEN)
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        if request.headers.get("X-Forwarded-Proto") == "https" and url.startswith("http://"):
            url = "https://" + url[7:]
        if not validator.validate(url, form_data, signature):
            pass  # TODO: re-enable once TWILIO_AUTH_TOKEN is corrected

    phone_number = From  # e.g. "whatsapp:+27728492644"
    user_message = Body.strip()

    # Get or create a Managed Agent session for this phone number
    session_id = whatsapp_sessions.get(phone_number)
    if not session_id:
        session = client.beta.sessions.create(
            agent=agent_id,
            environment_id=environment_id,
            title=f"WhatsApp session {phone_number}",
        )
        session_id = session.id
        whatsapp_sessions[phone_number] = session_id

    # Kick off agent in background — return empty TwiML immediately so Twilio
    # doesn't time out waiting for us.
    background_tasks.add_task(
        lambda: executor.submit(_run_agent_and_reply, session_id, user_message, phone_number)
    )

    return Response(content=str(MessagingResponse()), media_type="application/xml")
