# Shopify AI Shopping Agent
### Claude Managed Agents + Shopify Storefront MCP

A floating chat widget embedded in your Shopify theme, powered by Claude Managed Agents.
Customers can search products, manage their cart, and check out — all in natural language.

---

## Architecture

```
Browser (Shopify theme)
    │  chat messages (HTTP + SSE)
    ▼
FastAPI backend (localhost:8000 → exposed via ngrok)
    │  Claude Managed Agents API
    ▼
Anthropic Platform
    │  Shopify Storefront MCP
    ▼
your-store.myshopify.com/api/mcp
```

---

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://platform.claude.com/settings/keys) (with Managed Agents beta access)
- A Shopify development store
- [ngrok](https://ngrok.com/download) (to expose localhost to Shopify's storefront)

---

## Setup

### 1. Clone / create the project folder

```bash
mkdir shopify-ai-agent && cd shopify-ai-agent
# copy main.py, requirements.txt, .env.example, ai-shopping-assistant.liquid here
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:
```
ANTHROPIC_API_KEY=sk-ant-...
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
```

### 4. Start the backend

```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
✅ Agent created: agent_...
✅ Environment created: env_...
🛍️  Connected to Shopify store: your-store.myshopify.com
🟢 Ready — server is running
```

Verify it works:
```bash
curl http://localhost:8000/health
```

### 5. Expose localhost with ngrok

In a new terminal:
```bash
ngrok http 8000
```

Copy the **Forwarding** URL, e.g.:
```
https://abc123.ngrok-free.app
```

### 6. Add the chat widget to your Shopify theme

**Step A — Upload the snippet**

In Shopify Admin:
1. Go to **Online Store → Themes → Edit code**
2. Under **Snippets**, click **Add a new snippet**
3. Name it `ai-shopping-assistant`
4. Paste the contents of `ai-shopping-assistant.liquid`
5. Replace `YOUR-NGROK-URL` in the file with your actual ngrok URL:
   ```liquid
   {% assign backend_url = 'https://abc123.ngrok-free.app' %}
   ```
6. Save

**Step B — Render the snippet in your theme**

1. In the theme editor, open `layout/theme.liquid`
2. Just before `</body>`, add:
   ```liquid
   {% render 'ai-shopping-assistant' %}
   ```
3. Save

**Step C — Preview your store**

Open your store in a browser. You should see a chat bubble in the bottom-right corner. Click it and start shopping!

---

## How it works

| Step | What happens |
|------|-------------|
| Widget opens | Browser calls `POST /api/sessions` → creates a Claude Managed Agent session |
| Customer sends message | Browser calls `POST /api/sessions/{id}/chat` |
| Backend opens SSE stream | FastAPI streams events from the Anthropic platform |
| Claude calls Shopify tools | Agent uses `search_shop_catalog`, `update_cart`, `get_cart` automatically |
| Response streams back | Text chunks arrive in real time and appear in the chat bubble |

---

## File structure

```
shopify-ai-agent/
├── main.py                       # FastAPI backend
├── requirements.txt
├── .env.example
├── .env                          # your secrets (never commit this)
└── ai-shopping-assistant.liquid  # paste into Shopify theme snippets/
```

---

## Going to production

When you're ready to deploy the backend to a real server:

1. Deploy `main.py` to Railway, Render, Fly.io, or a VPS
2. Set environment variables on the server instead of `.env`
3. Update the `backend_url` in the liquid snippet to your production URL
4. Set `ALLOWED_ORIGINS=https://your-store.myshopify.com` in `.env`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chat widget doesn't appear | Check browser console for errors; verify ngrok is running |
| `Agent not ready yet` | Wait a few seconds and reload — agent is still initialising |
| CORS errors | Make sure `ALLOWED_ORIGINS=*` in `.env` during local dev |
| No products returned | Check `SHOPIFY_STORE_DOMAIN` in `.env` — no `https://`, no trailing slash |
| ngrok URL expired | Free ngrok URLs reset each session — update the liquid snippet with the new URL |
