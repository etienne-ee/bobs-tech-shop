# Bob's Tech Shop — AI Shopping Agent
### Build Log, Setup Guide & Troubleshooting Reference

---

## What This Is

A floating chat widget embedded in a Shopify storefront, powered by Claude Managed Agents. Customers can search for products, ask questions, and add items to their cart — all through natural language.

```
Browser (Shopify store)
    │  chat messages over HTTP + SSE
    ▼
FastAPI backend (localhost:8000, exposed via ngrok)
    │  Claude Managed Agents API
    ▼
Anthropic Platform
    │  Shopify Storefront MCP
    ▼
bobs-tech-shop-3.myshopify.com/api/mcp
```

---

## How It Works

| Step | What happens |
|------|-------------|
| Widget opens | Browser calls `POST /api/sessions` → creates a Claude Managed Agent session |
| Customer sends message | Browser calls `POST /api/sessions/{id}/chat` |
| Backend opens SSE stream | FastAPI streams events from the Anthropic platform |
| Claude calls Shopify tools | Agent uses the Shopify Storefront MCP to search products, update cart, etc. |
| Response streams back | Text chunks arrive in real time and appear in the chat bubble |

### Key components

- **`main.py`** — FastAPI backend. On startup it creates a Claude Managed Agent (with the Shopify MCP server attached) and a cloud environment. Each visitor gets their own session. Messages are streamed back as Server-Sent Events (SSE).
- **`ai-shopping-assistant.liquid`** — Shopify theme snippet. A self-contained chat bubble (HTML + CSS + JS) that talks to the FastAPI backend.
- **`.env`** — Secrets. Never commit this file.
- **ngrok** — Tunnels `localhost:8000` to a public HTTPS URL so Shopify's storefront can reach your local backend.

---

## File Structure

```
files/
├── main.py                        # FastAPI backend
├── requirements.txt               # Python dependencies
├── .env                           # Secrets (never commit)
├── ai-shopping-assistant.liquid   # Paste into Shopify theme snippets/
└── GUIDE.md                       # This file
```

---

## First-Time Setup

### Prerequisites
- Python 3.11+
- An Anthropic API key (with Managed Agents beta access) — get one at https://platform.claude.com/settings/keys
- A Shopify development store
- ngrok — install with `brew install ngrok`

---

### Step 1 — Create the `.env` file

Create a file called `.env` in the `files/` folder:

```
ANTHROPIC_API_KEY=sk-ant-...
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
ALLOWED_ORIGINS=*
```

Rules for `SHOPIFY_STORE_DOMAIN`:
- No `https://`
- No trailing slash
- Example: `bobs-tech-shop-3.myshopify.com`

---

### Step 2 — Create a virtual environment and install dependencies

```bash
cd /Users/etienne/Documents/EE-Projects/bobs-tech-shop/files
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

---

### Step 3 — Start the backend

```bash
venv/bin/uvicorn main:app --reload --port 8000
```

You should see:
```
✅ Agent created: agent_...
✅ Environment created: env_...
🛍️  Connected to Shopify store: your-store.myshopify.com
🟢 Ready — server is running
```

Verify it's working:
```bash
curl http://localhost:8000/health
```

---

### Step 4 — Start ngrok (in a new terminal window)

Register your auth token once (only needed the first time):
```bash
ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN
```

Then start the tunnel:
```bash
ngrok http 8000
```

You'll see a **Forwarding** line like:
```
Forwarding    https://congrats-octane-throwaway.ngrok-free.dev -> http://localhost:8000
```

Copy that `https://` URL — you'll need it in the next step.

> **Important:** Free ngrok URLs reset every time you restart ngrok. You must update the liquid snippet with the new URL each session.

---

### Step 5 — Update the liquid snippet with your ngrok URL

Open `ai-shopping-assistant.liquid` and update line 10:

```liquid
{% assign backend_url = 'https://your-ngrok-url.ngrok-free.app' %}
```

Replace the URL with the one ngrok gave you.

---

### Step 6 — Add the chat widget to your Shopify theme

**Upload the snippet:**
1. Shopify Admin → Online Store → Themes → Edit code
2. Under Snippets → click **Add a new snippet**
3. Name it exactly: `ai-shopping-assistant`
4. Delete the default content, paste the full contents of `ai-shopping-assistant.liquid`
5. Save

**Render it in your theme:**
1. Open `layout/theme.liquid`
2. Find `</body>` near the bottom
3. Add this line just before it:
   ```liquid
   {% render 'ai-shopping-assistant' %}
   ```
4. Save

**Test it:**
Open your store. A chat bubble should appear in the bottom-right corner. Click it and start chatting.

---

## How to Run It Again (After Initial Setup)

Every time you come back to work on this:

1. **Start the backend** (Terminal 1):
   ```bash
   cd /Users/etienne/Documents/EE-Projects/bobs-tech-shop/files
   venv/bin/uvicorn main:app --port 8000
   ```

2. **Start ngrok** (Terminal 2):
   ```bash
   ngrok http 8000
   ```

3. **Update the liquid snippet** with the new ngrok URL (it changes each session):
   - Edit line 10 of `ai-shopping-assistant.liquid`
   - Go to Shopify Admin → Themes → Edit code → Snippets → `ai-shopping-assistant`
   - Update the `backend_url` and save

4. **Hard refresh your store page** (`Cmd + Shift + R`) to clear any old sessions

---

## Errors We Hit During Setup (And Why)

### Error 1 — Missing `type` field on MCP server

**Error message:**
```
Failed to parse request: mcp_servers[0].type: Field required
```

**Why it happened:**
The original `main.py` had the MCP server defined like this:
```python
mcp_servers=[
    {
        "url": f"https://{SHOPIFY_STORE_DOMAIN}/api/mcp",
        "name": "shopify_storefront",
    }
]
```

The Anthropic API requires a `"type"` field on every MCP server object.

**Fix:**
```python
mcp_servers=[
    {
        "type": "url",   # ← this was missing
        "url": f"https://{SHOPIFY_STORE_DOMAIN}/api/mcp",
        "name": "shopify_storefront",
    }
]
```

---

### Error 2 — MCP server declared but not referenced in tools

**Error message:**
```
Agent has invalid configuration: mcp_servers [shopify_storefront] declared but no mcp_toolset in tools references them
```

**Why it happened:**
The agent was created with an MCP server in `mcp_servers`, but the `tools` list only had the built-in agent toolset and no entry that actually wired up the Shopify MCP server.

**Fix:**
Add an `mcp_toolset` entry to `tools` that references the server by name:
```python
tools=[
    {"type": "agent_toolset_20260401"},
    {
        "type": "mcp_toolset",
        "mcp_server_name": "shopify_storefront",
        "default_config": {"permission_policy": {"type": "always_allow"}},
    },
],
```

---

### Error 3 — Tool confirmation required (product search always failing)

**Error message:**
```
Invalid user.message event at events[0]: waiting on responses to events [...];
only `user.tool_confirmation`, `user.custom_tool_result`, or `user.interrupt` may be sent
```

**Why it happened:**
This was the trickiest one. By default, the Managed Agents platform requires explicit confirmation before executing MCP tool calls. The flow looks like this:

1. Customer asks "show me laptops"
2. Agent decides to call the Shopify MCP tool
3. Platform pauses and sends a tool confirmation request event
4. Platform waits for the backend to send back a `user.tool_confirmation` event
5. Our backend never sent that confirmation — it just tried to send the next user message
6. Platform rejected it with a 400 error
7. Backend sent `{"type": "error"}` to the frontend → "Something went wrong"

This caused every product search and cart action to fail, while plain conversational messages (like "hello") worked fine because they didn't trigger any tool calls.

**Fix:**
Set `permission_policy` to `always_allow` on the MCP toolset. This tells the platform to auto-approve all Shopify tool calls without waiting for confirmation:
```python
"default_config": {"permission_policy": {"type": "always_allow"}}
```

---

### Error 4 — Stale session after server restart

**Symptom:**
After restarting the backend, the chat widget kept failing even though the backend was healthy.

**Why it happened:**
The chat widget stores the `sessionId` in a JavaScript variable. When the backend restarts, it creates a new agent and environment. The old session (from the previous backend run) is now tied to a stale agent, and the platform rejects new messages sent to it.

**Fix:**
Hard refresh the store page (`Cmd + Shift + R`) after every backend restart. This clears the JavaScript variable and forces a new session to be created with the current agent.

---

## Troubleshooting Quick Reference

| Problem | Cause | Fix |
|---------|-------|-----|
| Chat bubble doesn't appear | Liquid snippet not added to `theme.liquid`, or ngrok not running | Check browser console; verify both are running |
| "Agent not ready yet" | Backend still starting up | Wait a few seconds and reload |
| "Something went wrong" on every message | Stale session from old backend | Hard refresh (`Cmd + Shift + R`) |
| "Something went wrong" only on product searches | MCP tool confirmation not set to always_allow | Add `permission_policy: always_allow` to mcp_toolset config |
| CORS errors in browser | `ALLOWED_ORIGINS` not set | Set `ALLOWED_ORIGINS=*` in `.env` for local dev |
| ngrok says "offline" or URL not working | ngrok not running, or URL changed | Restart `ngrok http 8000` and update the liquid snippet |
| No products returned | Wrong store domain | Check `SHOPIFY_STORE_DOMAIN` in `.env` — no `https://`, no slash |

---

## WhatsApp Integration (Twilio)

The backend also handles WhatsApp messages via Twilio, giving customers a second channel to talk to the same shopping agent.

### How it works

```
Customer WhatsApp message
    │
    ▼
Twilio → POST /whatsapp (ngrok URL)
    │
    ▼
FastAPI returns empty TwiML immediately (avoids Twilio's 15s timeout)
    │
    ▼
Background task → Claude Managed Agent → _send_whatsapp_reply (Twilio REST API)
```

Each WhatsApp phone number gets its own Managed Agent session (stored in `whatsapp_sessions` dict — in-memory, resets on restart).

The products JSON block is stripped from replies — product cards are meaningless over WhatsApp.

### Environment variables needed

Add these to `.env`:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=your_api_key_secret
TWILIO_WHATSAPP_FROM=whatsapp:+12602691164
```

> **Note:** We connect via Twilio API key (SID + secret) rather than the Auth Token, because the Auth Token is not accessible. The `TwilioClient` is initialised as `TwilioClient(api_key_sid, api_key_secret, account_sid)`. Webhook signature validation is currently disabled (`pass` in the validator block) because `RequestValidator` requires the Auth Token — re-enable it if the Auth Token becomes available.

### Twilio setup

1. In the Twilio console, go to **Messaging → Senders → WhatsApp senders**
2. Set the webhook URL for incoming messages to: `https://your-ngrok-url.ngrok-free.app/whatsapp`
3. Method: `HTTP POST`
4. Remember to update this URL every session (ngrok URL changes each time)

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| No reply from bot | Agent error or Twilio REST call failed | Check server logs for `[whatsapp]` entries |
| Reply never arrives | ngrok URL in Twilio console is stale | Update webhook URL in Twilio console |
| Old session answers for new customer | `whatsapp_sessions` not cleared | Restart the backend |

---

## Going to Production

When ready to deploy the backend to a real server:

1. Deploy `main.py` to Railway, Render, Fly.io, or a VPS
2. Set environment variables on the server (not in `.env`)
3. Update the `backend_url` in the liquid snippet to your production URL
4. Set `ALLOWED_ORIGINS=https://your-store.myshopify.com` in production
5. No more ngrok needed — the production URL is permanent

---

## Store Details

- **Store:** bobs-tech-shop-3.myshopify.com
- **Backend files:** `/Users/etienne/Documents/EE-Projects/bobs-tech-shop/files/`
- **Python venv:** `files/venv/`
