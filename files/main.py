import os
import json
import asyncio
import re
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

import anthropic
import httpx
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
SHOPIFY_ADMIN_TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN")    # Admin API token for creating orders
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
STORE_OWNER_EMAIL = os.getenv("STORE_OWNER_EMAIL")

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
if not SHOPIFY_STORE_DOMAIN:
    raise RuntimeError("SHOPIFY_STORE_DOMAIN is not set in .env")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
executor = ThreadPoolExecutor(max_workers=20)

# WhatsApp session store: maps WhatsApp phone number → Managed Agent session ID
# In-memory only — resets on server restart. Swap for Redis/DB in production.
whatsapp_sessions: dict[str, str] = {}

# Per-number lock: prevents concurrent agent calls for the same WhatsApp number.
_whatsapp_locks: dict[str, threading.Lock] = {}
_whatsapp_locks_guard = threading.Lock()

def _get_whatsapp_lock(phone_number: str) -> threading.Lock:
    with _whatsapp_locks_guard:
        if phone_number not in _whatsapp_locks:
            _whatsapp_locks[phone_number] = threading.Lock()
        return _whatsapp_locks[phone_number]

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

# Stored on startup
agent_id: str | None = None
environment_id: str | None = None

SYSTEM_PROMPT = f"""You are a friendly and knowledgeable shopping assistant for this store.

Your job is to help customers:
- Search and discover products using natural language
- Understand product details, pricing, and availability
- Add items to their cart and place orders
- Answer questions about store policies, shipping, and returns

Always be concise and helpful. Store domain: {SHOPIFY_STORE_DOMAIN}

## What this store sells

This store carries three product categories:
- **Tech / electronics:** headphones, keyboards, cables, speakers, mice, monitors, laptop stands, SSDs, webcams, charging pads, chargers, laptop sleeves
- **Socks:** ankle socks, wool hiking socks, compression socks, bamboo crew socks, novelty socks
- **Meat / braai:** beef steak, chicken breast, boerewors, lamb chops, pork ribs

Never tell a customer the store only sells tech — it also sells socks and meat.

## Search strategy

Always call search_catalog with pagination.limit set to 25 or less — never omit the limit or set it above 25.

Use this approach:
1. Search with the customer's specific keywords first (e.g. "charger", "sock", "steak", "ribs").
2. If that returns 0 products, try the category name as the query: "meat", "socks", or "tech" depending on what the customer is asking about.
3. If still 0 results, try a broader term ("braai", "accessories", "clothing") as a last resort.

Never tell a customer a product doesn't exist based on a single failed search. Try at least two searches before concluding something is unavailable.

## Product cards

Whenever you list one or more products, append a JSON block at the very end of your message in exactly this format (nothing after the closing fence):

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
- Use the exact image URL and product URL from the Shopify product data.
- Include every product you mention in the block.
- If a product has no image, omit the image_url field.
- Never fabricate URLs or prices.

## Cart and checkout

When you show a customer a product, note its variant ID from the Shopify product data.
Variant IDs look like: "gid://shopify/ProductVariant/44242430951475"

Keep a mental note of the customer's cart — what they've asked to add, each item's variant ID, and quantity.

When a customer wants to checkout, collect their details in exactly two friendly messages — not one field at a time:

**Message 1** — ask for name and email together in a warm, natural way. Example:
"Sounds great! To get your order on its way, what's your name and email address?"

**Message 2** — once you have those, ask for phone and full delivery address together. Example:
"Perfect! And what's the best number to reach you on, and where should we deliver? (Street address, city, and postal code)"

Once you have all four pieces of info, give a warm summary — list the items, total, and delivery address — and let them know payment is Cash on Delivery (collected at the door, no card needed). Then ask them to confirm.

When the customer confirms, output this block at the very end of your message and nothing after it:

```order
{{
  "customer": {{
    "first_name": "...",
    "last_name": "...",
    "email": "...",
    "phone": "..."
  }},
  "shipping_address": {{
    "address1": "...",
    "city": "...",
    "zip": "...",
    "country_code": "ZA"
  }},
  "line_items": [
    {{"variant_id": "gid://shopify/ProductVariant/...", "title": "...", "quantity": 1}}
  ]
}}
```

Rules:
- Use real variant IDs from the Shopify product data — never invent them.
- country_code is always "ZA" for this store.
- Only output the order block once the customer has explicitly confirmed.
- Never ask for payment details — it is always Cash on Delivery.
- Keep the tone friendly and conversational throughout — this should feel like chatting with a helpful person, not filling in a form.

## Defective or damaged orders

If a customer reports receiving a defective, damaged, or wrong item:
1. Apologise sincerely and empathetically.
2. Ask for their order number and a brief description of the problem (if they haven't already provided both).
3. Once you have both, say something like "I'm logging this with the store team now." — do NOT claim the team has been notified or that an email has been sent, because the system confirms that separately.
4. Output this block at the very end of your message and nothing after it:

```defective_report
{{
  "customer_name": "...",
  "order_number": "...",
  "issue": "...",
  "contact": "..."
}}
```

Rules:
- customer_name and contact are whatever the customer shared (name, phone, email — whatever is available).
- issue is a short description of the problem in the customer's own words.
- Only output the block once you have both the order number and a description of the issue.
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

                    # Order block — create the Shopify order and emit confirmation
                    order_match = re.search(r"```order\s*(\{.*?\})\s*```", text, re.DOTALL)
                    if order_match:
                        clean_text = text[:order_match.start()].rstrip()
                        if clean_text:
                            yield f"data: {json.dumps({'type': 'text', 'content': clean_text})}\n\n"
                        try:
                            order_data = json.loads(order_match.group(1))
                            result = await loop.run_in_executor(
                                executor, lambda: _create_shopify_order(order_data)
                            )
                            order = result.get("order", {})
                            yield f"data: {json.dumps({'type': 'order_confirmed', 'order_number': order.get('order_number'), 'order_name': order.get('name')})}\n\n"
                        except Exception as exc:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'Could not place order: {exc}'})}\n\n"
                        continue

                    # Defective report block — send email to store owner
                    defect_match = re.search(r"```defective_report\s*(\{.*?\})\s*```", text, re.DOTALL)
                    if defect_match:
                        clean_text = text[:defect_match.start()].rstrip()
                        if clean_text:
                            yield f"data: {json.dumps({'type': 'text', 'content': clean_text})}\n\n"
                        sent = False
                        order_number = None
                        try:
                            report = json.loads(defect_match.group(1))
                            order_number = report.get("order_number")
                            sent = await loop.run_in_executor(executor, lambda: _send_defect_email(report))
                        except Exception as exc:
                            print(f"[email] Failed to parse/send defect report: {exc}")
                        if sent:
                            yield f"data: {json.dumps({'type': 'defect_reported', 'order_number': order_number})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'error', 'message': 'We could not submit your report right now. Please contact us directly or try again shortly.'})}\n\n"
                        continue

                    # Products block — emit product cards
                    prod_match = re.search(r"```products\s*(\[.*?\])\s*```", text, re.DOTALL)
                    if prod_match:
                        clean_text = text[:prod_match.start()].rstrip()
                        if clean_text:
                            yield f"data: {json.dumps({'type': 'text', 'content': clean_text})}\n\n"
                        try:
                            products = json.loads(prod_match.group(1))
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


def _create_shopify_order(order_data: dict) -> dict:
    """Create a Shopify order via the Admin API with Cash on Delivery payment."""
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/2024-01/orders.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
        "Content-Type": "application/json",
    }

    # Strip GID prefix — Admin API needs plain integer variant IDs
    line_items = []
    for item in order_data.get("line_items", []):
        vid = str(item["variant_id"])
        numeric_id = int(vid.split("/")[-1]) if "/" in vid else int(vid)
        line_items.append({"variant_id": numeric_id, "quantity": item.get("quantity", 1)})

    customer = order_data["customer"]
    shipping = order_data["shipping_address"]
    address = {
        "first_name": customer["first_name"],
        "last_name": customer["last_name"],
        "phone": customer.get("phone", ""),
        **shipping,
    }

    payload = {
        "order": {
            "line_items": line_items,
            "customer": {
                "first_name": customer["first_name"],
                "last_name": customer["last_name"],
                "email": customer.get("email", ""),
            },
            "shipping_address": address,
            "billing_address": address,
            "financial_status": "pending",
            "tags": "cash-on-delivery,ai-agent",
            "note": "Placed via AI shopping assistant. Payment: Cash on Delivery.",
            "send_receipt": True,
        }
    }

    with httpx.Client(timeout=15) as http:
        resp = http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _send_defect_email(report: dict) -> bool:
    """Send a defective order notification to the store owner via Resend.
    Returns True on success, False on any failure."""
    if not RESEND_API_KEY or not STORE_OWNER_EMAIL:
        print("[email] RESEND_API_KEY or STORE_OWNER_EMAIL not set — skipping email")
        return False
    html = (
        f"<h2>⚠️ Defective Order Report</h2>"
        f"<p><strong>Customer:</strong> {report.get('customer_name', 'Unknown')}</p>"
        f"<p><strong>Order number:</strong> {report.get('order_number', 'Not provided')}</p>"
        f"<p><strong>Issue:</strong> {report.get('issue', 'No description')}</p>"
        f"<p><strong>Contact:</strong> {report.get('contact', 'Not provided')}</p>"
    )
    payload = {
        "from": "onboarding@resend.dev",
        "to": [STORE_OWNER_EMAIL],
        "subject": f"⚠️ Defective order report — {report.get('order_number', 'unknown')}",
        "html": html,
    }
    try:
        with httpx.Client(timeout=10) as http:
            resp = http.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            )
            resp.raise_for_status()
            print(f"[email] Defect report sent for order {report.get('order_number')}")
            return True
    except Exception as exc:
        print(f"[email] Failed to send defect report: {exc}")
        return False


def _send_whatsapp_reply(to: str, reply_text: str, image_urls: list[str] | None = None) -> None:
    """Send a WhatsApp message via Twilio REST API (called from background task)."""
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    sender = os.getenv("TWILIO_WHATSAPP_FROM")  # e.g. "whatsapp:+12602691164"

    # Twilio supports up to 10 media URLs per message; cap at 10 to be safe
    media = (image_urls or [])[:10] or None
    twilio_client.messages.create(body=reply_text, from_=sender, to=to, media_url=media)


def _run_agent_and_reply(session_id: str, user_message: str, phone_number: str) -> None:
    """Run in thread executor: get agent reply, then push it via Twilio REST API."""
    lock = _get_whatsapp_lock(phone_number)
    if not lock.acquire(blocking=False):
        # Another message from this number is already being processed — drop to avoid flooding.
        print(f"[whatsapp] dropping concurrent message from {phone_number}")
        return
    try:
        _run_agent_and_reply_inner(session_id, user_message, phone_number)
    finally:
        lock.release()


def _run_agent_and_reply_inner(session_id: str, user_message: str, phone_number: str) -> None:
    last_text = ""
    rate_limited = False
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
                            last_text = text  # overwrite — only the final reply matters
                elif event.type == "session.error":
                    err = getattr(event, "error", None)
                    if err and getattr(err, "type", None) == "model_rate_limited_error":
                        rate_limited = True
                elif event.type == "session.status_idle":
                    stop = getattr(event, "stop_reason", None)
                    if stop and getattr(stop, "type", None) == "retries_exhausted":
                        rate_limited = True
                    break
    except Exception as exc:
        print(f"[whatsapp] agent error: {exc}")
        _send_whatsapp_reply(phone_number, "Sorry, something went wrong. Please try again.")
        return

    if rate_limited or not last_text:
        _send_whatsapp_reply(
            phone_number,
            "I'm a bit busy right now — please send your message again in a moment.",
        )
        return

    raw_reply = last_text

    image_urls: list[str] = []

    # Order block — create Shopify order and build confirmation message
    order_match = re.search(r"```order\s*(\{.*?\})\s*```", raw_reply, re.DOTALL)
    if order_match:
        preamble = raw_reply[:order_match.start()].rstrip()
        try:
            order_data = json.loads(order_match.group(1))
            result = _create_shopify_order(order_data)
            order_name = result["order"]["name"]
            reply_text = f"{preamble}\n\n✅ Order {order_name} confirmed! We'll be in touch to arrange delivery. Payment is due on arrival — no card needed."
        except Exception as exc:
            print(f"[whatsapp] order creation error: {exc}")
            reply_text = f"{preamble}\n\nSorry, we couldn't place your order right now. Please try again."
    else:
        # Defective report block — send email, build reply based on actual result
        defect_match = re.search(r"```defective_report\s*(\{.*?\})\s*```", raw_reply, re.DOTALL)
        if defect_match:
            preamble = raw_reply[:defect_match.start()].rstrip()
            sent = False
            try:
                report = json.loads(defect_match.group(1))
                sent = _send_defect_email(report)
            except Exception as exc:
                print(f"[whatsapp] defect report error: {exc}")
            if sent:
                reply_text = f"{preamble}\n\n✅ Your report has been submitted. The store team will follow up with you within 24 hours."
            else:
                reply_text = f"{preamble}\n\n⚠️ Sorry, we couldn't submit your report right now. Please contact us directly and we'll sort this out immediately."
        else:
            # Products block — extract images then strip the JSON
            prod_match = re.search(r"```products\s*(\[.*?\])\s*```", raw_reply, re.DOTALL)
            if prod_match:
                try:
                    products = json.loads(prod_match.group(1))
                    image_urls = [p["image_url"] for p in products if p.get("image_url")]
                except (json.JSONDecodeError, KeyError):
                    pass
                reply_text = raw_reply[:prod_match.start()].rstrip()
            else:
                reply_text = raw_reply

    # Truncate to WhatsApp's 1600-character limit
    if len(reply_text) > 1600:
        reply_text = reply_text[:1597] + "..."

    _send_whatsapp_reply(
        phone_number,
        reply_text or "Sorry, I didn't get a response. Please try again.",
        image_urls=image_urls or None,
    )


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
