# Bob's Tech Shop — AI Shopping Agent: Complete Technical Overview

---

## Table of Contents

1. [What this is](#1-what-this-is)
2. [Architecture at a glance](#2-architecture-at-a-glance)
3. [The two customer channels](#3-the-two-customer-channels)
4. [How to get it running](#4-how-to-get-it-running)
5. [How the chat widget works](#5-how-the-chat-widget-works)
6. [How Claude Managed Agents works](#6-how-claude-managed-agents-works)
7. [How the Shopify MCP connection works](#7-how-the-shopify-mcp-connection-works)
8. [How the agent finds products — the search deep dive](#8-how-the-agent-finds-products--the-search-deep-dive)
9. [What we did to make product search better](#9-what-we-did-to-make-product-search-better)
10. [How the WhatsApp channel works](#10-how-the-whatsapp-channel-works)
11. [Key things that will break you (and why)](#11-key-things-that-will-break-you-and-why)

---

## 1. What this is

Bob's Tech Shop's AI shopping assistant is a natural-language chat interface embedded directly in the Shopify storefront. Customers can:

- Ask for products in plain English ("show me a laptop sleeve")
- Get product recommendations with images, prices, and links
- Add items to their cart
- Ask about the store

The same AI assistant is also available over **WhatsApp** via Twilio — customers can send a WhatsApp message to the store's number and get the same experience without opening a browser.

The "intelligence" is Claude (Anthropic's AI model), connected to the live Shopify product catalogue through an MCP server that Shopify hosts. Claude reads and acts on real inventory data — it never guesses or makes up products.

---

## 2. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│  CUSTOMER CHANNELS                                               │
│                                                                 │
│  Browser (Shopify store)        WhatsApp (customer's phone)     │
│     │ HTTP + SSE stream               │ Twilio webhook          │
└─────┼───────────────────────────────┼─────────────────────────┘
      │                               │
      ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI backend  (localhost:8000, exposed via ngrok)            │
│                                                                 │
│  POST /api/sessions        → creates a new Claude session       │
│  POST /api/sessions/{id}/chat → streams Claude's reply (SSE)    │
│  POST /whatsapp            → Twilio webhook receiver            │
└─────────────────────────────┬───────────────────────────────────┘
                              │ Anthropic Managed Agents API
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Anthropic Platform                                             │
│                                                                 │
│  Claude Agent (Haiku 4.5)                                       │
│    → receives customer message                                  │
│    → decides which Shopify tools to call                        │
│    → calls tools, reads results, forms response                 │
│    → streams response back                                      │
│                                                                 │
│  Cloud Environment (compute for tool execution)                 │
└─────────────────────────────┬───────────────────────────────────┘
                              │ MCP protocol (HTTPS)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Shopify Storefront MCP                                         │
│  https://bobs-tech-shop-3.myshopify.com/api/mcp                 │
│                                                                 │
│  Hosted by Shopify. Exposes tools like:                         │
│    search_catalog   → search products by query string           │
│    add_to_cart      → add a variant to the cart                 │
│    get_cart         → read current cart contents                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. The two customer channels

| | Chat widget | WhatsApp |
|---|---|---|
| Entry point | Floating chat bubble on the store | Customer's WhatsApp app |
| Backend route | `POST /api/sessions/{id}/chat` | `POST /whatsapp` |
| Response method | SSE streaming (text appears in real time) | Twilio REST API (single message after agent finishes) |
| Product cards | Yes — images, prices, links rendered in the widget | No — the `products` JSON block is stripped, plain text only |
| Session storage | JavaScript variable in the browser | In-memory Python dict keyed by phone number |
| Session lifetime | Until hard refresh or browser close | Until server restart |

---

## 4. How to get it running

### Prerequisites

- Python 3.11+
- An Anthropic API key with Managed Agents access — get one at https://platform.claude.com/settings/keys
- A Shopify development store
- ngrok — `brew install ngrok`

### Step 1 — Create `.env`

Create `files/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
ALLOWED_ORIGINS=*
```

No `https://`, no trailing slash on the domain.

### Step 2 — Install dependencies

```bash
cd files
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

> **Note:** The venv's `uvicorn` shebang embeds its creation path. If you move the project folder, call Python directly: `venv/bin/python3.14 -m uvicorn main:app --port 8000`

### Step 3 — Start the backend

```bash
venv/bin/python3.14 -m uvicorn main:app --port 8000
```

On first start you'll see:
```
🚀 Starting up — creating Claude Managed Agent...
✅ Agent created: agent_...
✅ Environment created: env_...
💾 IDs saved to .env
🛍️  Connected to Shopify store: your-store.myshopify.com
🟢 Ready — server is running
```

The agent and environment IDs are persisted to `.env`. On subsequent restarts, the backend reuses them rather than creating new ones — this is fast and avoids accumulating stale resources.

### Step 4 — Start ngrok

```bash
ngrok http 8000
```

Copy the `https://...ngrok-free.app` URL. This is your public backend URL for the current session. It changes every time you restart ngrok.

### Step 5 — Add the chat widget to Shopify

1. Shopify Admin → Online Store → Themes → Edit code
2. Snippets → Add new snippet → name it `ai-shopping-assistant`
3. Paste the contents of `ai-shopping-assistant.liquid`
4. Update line 10 with your ngrok URL: `{% assign backend_url = 'https://your-url.ngrok-free.app' %}`
5. Open `layout/theme.liquid`, add `{% render 'ai-shopping-assistant' %}` just before `</body>`

### Step 6 — Test

Open the store. A chat bubble appears bottom-right. Click it and ask something like "what do you have?".

### Every subsequent session

1. Start backend: `venv/bin/python3.14 -m uvicorn main:app --port 8000`
2. Start ngrok: `ngrok http 8000`
3. Update the ngrok URL in the Shopify snippet
4. Hard refresh the store: `Cmd + Shift + R`

---

## 5. How the chat widget works

The widget is a single self-contained Shopify liquid snippet (`ai-shopping-assistant.liquid`). It injects HTML, CSS, and JavaScript into every page of the store.

**Session lifecycle:**
1. When the bubble is clicked for the first time, the JS calls `POST /api/sessions` on the backend
2. The backend creates a Claude Managed Agent session and returns a `session_id`
3. The `session_id` is stored in a JS variable for the lifetime of the page

**Message flow:**
1. Customer types a message and hits send
2. JS calls `POST /api/sessions/{session_id}/chat` with the message body
3. The backend opens a **Server-Sent Events (SSE)** stream back to the browser
4. As Claude responds, the backend pushes JSON events over the stream:
   - `{"type": "text", "content": "..."}` — a chunk of text (appears in real time)
   - `{"type": "tool", "name": "search_catalog"}` — Claude is calling a Shopify tool
   - `{"type": "products", "products": [...]}` — product card data
   - `{"type": "done"}` — Claude finished responding
   - `{"type": "error", "message": "..."}` — something went wrong

**Product cards:**
Claude is instructed via the system prompt to append a fenced JSON block to any message that mentions products:

````
```products
[
  {
    "title": "iPhone Charger",
    "price": "R 500.00",
    "image_url": "https://cdn.shopify.com/...",
    "url": "https://bobs-tech-shop-3.myshopify.com/products/iphone-charger"
  }
]
```
````

The backend strips this block from the text stream and emits it as a separate `products` event. The widget renders image cards from this data — real product photos, prices, and clickable links to the product page.

---

## 6. How Claude Managed Agents works

Claude Managed Agents is an Anthropic platform feature that lets you run a persistent, stateful Claude agent with a defined toolset. Instead of calling the Claude API directly per-message, you:

1. **Create an Agent** — define the model, system prompt, and tools once
2. **Create an Environment** — the compute context where tools run
3. **Create Sessions** — one per customer conversation; sessions carry full conversation history
4. **Stream events** — send a message, receive a stream of events as Claude thinks and responds

Key concepts:

| Concept | What it is |
|---|---|
| Agent | The configured AI: model + system prompt + tools. Created once on startup, reused. |
| Environment | The cloud runtime where tool calls execute. Created once, reused. |
| Session | One customer conversation. Maintains context across multiple messages. |
| Events | The streaming protocol: `agent.thinking`, `agent.mcp_tool_use`, `agent.mcp_tool_result`, `agent.message`, `session.status_idle` |

In `main.py`, the agent and environment are created (or reused from `.env`) in the FastAPI lifespan. Each visitor gets their own session via `POST /api/sessions`.

---

## 7. How the Shopify MCP connection works

Shopify hosts an MCP server at every storefront URL:
```
https://your-store.myshopify.com/api/mcp
```

MCP (Model Context Protocol) is an open protocol that lets AI models call external tools through a standardised interface. Shopify's implementation exposes tools for searching the product catalogue, reading cart state, and adding items to cart.

The agent is configured with this MCP server as a **toolset**:

```python
mcp_servers=[{
    "type": "url",
    "url": f"https://{SHOPIFY_STORE_DOMAIN}/api/mcp",
    "name": "shopify_storefront",
}],
tools=[
    {"type": "agent_toolset_20260401"},
    {
        "type": "mcp_toolset",
        "mcp_server_name": "shopify_storefront",
        "default_config": {"permission_policy": {"type": "always_allow"}},
    },
],
```

The `permission_policy: always_allow` is critical — without it, every tool call requires explicit confirmation from the backend before it executes, which we never send, causing every product search to return a 400 error.

When Claude decides to search for products, it calls the `search_catalog` tool on this MCP server. The call goes from the Anthropic platform directly to Shopify's servers over HTTPS — the FastAPI backend is not involved in that exchange.

---

## 8. How the agent finds products — the search deep dive

### The tool

The core Shopify tool is `search_catalog`. It accepts:

```json
{
  "catalog": {
    "query": "string",
    "pagination": {
      "limit": 25
    }
  }
}
```

The MCP server forwards this to Shopify's product search index and returns a list of matching products with full data: titles, descriptions, prices, images, variant IDs, URLs.

### How Shopify indexes products

Shopify's `search_catalog` searches across:
- Product **title** (e.g. "Macbook sleeve")
- Product **description** (e.g. "Protective cover for Macbooks")
- Product **tags** (set in Shopify admin)
- Product **vendor** and **product type** fields

This means the search is only as good as the product data in Shopify. If a product has no tags, a minimal description, and a generic title, it will be hard to find with anything other than its exact name.

### The critical discovery: what actually returns results

We ran a controlled experiment sending 7 different queries to the agent and logging every raw MCP call and result. Here's what we found for this store (which has 3 products: Sock, Macbook sleeve, iPhone Charger):

| Query string sent to `search_catalog` | Products returned |
|---|---|
| `"all products"` | **0** — the phrase matches nothing in product data |
| `"laptops"` | **0** — no laptops in the store |
| `"laptop computer"` | **0** |
| `"gaming"` | **0** |
| `"game controller headset console"` | **0** |
| `"electronics"` | **0** |
| `"headphones"` | **0** |
| `"audio"` | **0** |
| **`"tech"`** | **3** — all products returned |
| **`"a"`** | **3** — all products returned |

The key insight: **short, store-matched terms return the full catalogue**. `"tech"` works because Shopify's search index associates these products with the store's category or tags. `"a"` works as a single-character wildcard that matches everything in the index.

Specific category terms that don't map to actual product metadata return nothing — even if the store sells something *related*. Searching `"laptops"` returns 0 results even though the store sells a "Macbook sleeve", because the word "laptop" appears nowhere in that product's Shopify data.

### What the agent used to do (before our fix)

When a customer asked "show me laptops", the agent would:
1. Search `query: "laptops"` → 0 results
2. Search `query: "laptop computer"` → 0 results  
3. Search `query: "computer electronics"` → 0 results
4. Search `query: "tech"` → 3 results (it eventually stumbled on this!)
5. Tell the customer: "We don't have laptops, but here's what we do have..."

This worked by accident. The agent was spending 3–4 tool calls finding the fallback. For "all products" queries, it would sometimes pass `limit: 250` which returns everything in one slow call.

---

## 9. What we did to make product search better

### The problem

Two failure modes:
1. **Too broad** — agent fetches with `limit: 250`, getting everything. Slow.
2. **Too specific** — agent searches for a category term that doesn't match any product data. Returns 0, agent declares item out of stock.

### The fix: system prompt search strategy

We added explicit search instructions to the agent's system prompt:

```
## Search strategy

Always call search_catalog with pagination.limit set to 25 or less — never omit
the limit or set it above 25.

Use this two-step approach:
1. Search with the customer's specific keywords first (e.g. "charger", "sleeve", "sock").
2. If that returns 0 products, do a fallback search using the query "tech" with limit 25 —
   this reliably returns the full catalog for this store. Then filter the results by hand
   to find the best match for what the customer asked for.

Never tell a customer a product doesn't exist based on a single failed search. Always
try the fallback before concluding something is out of stock.
```

### What this changes

| Before | After |
|---|---|
| Agent might use `limit: 250` | Hard cap of `limit: 25` |
| 3–4 tool calls to find products | 1–2 tool calls (specific → "tech" fallback) |
| Agent might give up and say "not in stock" | Agent always tries the "tech" fallback first |
| Result: slow and unreliable | Result: fast and consistent |

### Why "tech" is the magic word for this store

The Shopify search index for this store maps its products to a "tech accessories" category. The word "tech" appears to match at the store/category level, not just in individual product titles. This is specific to this store's configuration — for a different store you would identify a different reliable broad-search term through the same kind of query experiment.

### How to update the search strategy for a different store

1. Run `search_experiment.py` against the new store
2. Look at the `agent.mcp_tool_result` events to find which query strings return all products
3. Update the fallback query in the system prompt (`"tech"` → whatever works)
4. Clear `AGENT_ID` and `ENVIRONMENT_ID` from `.env` and restart the backend so the new system prompt takes effect

---

## 10. How the WhatsApp channel works

### Architecture

```
Customer WhatsApp message
    │
    ▼
Twilio receives it → POST /whatsapp (your ngrok URL)
    │
    ▼
FastAPI immediately returns empty TwiML (avoids Twilio's 15-second timeout)
    │
    ▼
Background task → Claude Managed Agent → agent reply
    │
    ▼
Twilio REST API → sends reply to customer's WhatsApp
```

Twilio has a hard 15-second timeout: if your webhook doesn't respond within 15 seconds, it gives up. Claude often takes longer than that to think and search products. The solution is to return an empty TwiML response immediately, then send the actual reply via a separate Twilio REST API call once the agent finishes.

### Session management

Each unique WhatsApp phone number gets its own Claude session, stored in an in-memory dict:

```python
whatsapp_sessions: dict[str, str] = {}
# key: "whatsapp:+27728492644"
# value: session ID like "sesn_01..."
```

This means a returning customer picks up the conversation where they left off — within the same server session. The dict resets on backend restart.

### Differences from the chat widget

- **No product cards** — the `products` JSON block is stripped from replies. Product images and links are meaningless over text messaging. The agent responds in plain text only.
- **1600 character limit** — WhatsApp/Twilio limits messages to 1600 characters. Long responses are truncated with `"..."`.
- **No streaming** — the customer waits for the full reply before receiving anything (unlike the widget where text appears in real time).

### Environment variables needed

Add these to `.env`:

```
TWILIO_ACCOUNT_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_or_api_key_secret
TWILIO_WHATSAPP_FROM=whatsapp:+12602691164
```

Set the Twilio webhook URL to `https://your-ngrok-url.ngrok-free.app/whatsapp` (Method: POST) in the Twilio console under Messaging → Senders → WhatsApp senders. Update this every session since the ngrok URL changes.

---

## 11. Key things that will break you (and why)

### After every backend restart: hard refresh the store

The `session_id` lives in a JavaScript variable. After a restart, the backend has a new agent. The old session ID is invalid and every message will error. `Cmd + Shift + R` wipes the variable and forces a new session.

### Changing the system prompt requires a new agent

The system prompt is baked into the agent at creation time. If you edit `SYSTEM_PROMPT` in `main.py`, you must force-create a new agent:

1. Clear `AGENT_ID=` and `ENVIRONMENT_ID=` in `.env`
2. Restart the backend — it will create a fresh agent with the new prompt

### The MCP must have `permission_policy: always_allow`

Without it, every tool call waits for a confirmation event from the backend. Since the backend never sends one, every product search fails with a 400 error. Conversational messages (like "hello") still work, making this confusing to debug.

### ngrok URL changes every session

Both the Shopify liquid snippet (`backend_url`) and the Twilio webhook URL must be updated each time you restart ngrok. Free ngrok URLs are not persistent.

### Moving the project folder breaks the venv

The `uvicorn` binary in `venv/bin/` has a shebang pointing to the absolute Python path at the time the venv was created. If the project moves, call Python directly:

```bash
venv/bin/python3.14 -m uvicorn main:app --port 8000
```

---

*Last updated: May 2026*
