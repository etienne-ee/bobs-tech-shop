#!/usr/bin/env python3
import os, time, httpx
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DOMAIN  = os.getenv("SHOPIFY_STORE_DOMAIN")
TOKEN   = os.getenv("SHOPIFY_ADMIN_TOKEN")
URL     = f"https://{DOMAIN}/admin/api/2024-01/products.json"
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

PRODUCTS = [
    {
        "title": "Ankle Socks 3-Pack (White)",
        "body_html": "Cushioned cotton ankle socks, breathable and durable.",
        "vendor": "SockCo", "product_type": "Socks",
        "tags": "socks, ankle, white, cotton, clothing",
        "options": [{"name": "Size"}],
        "variants": [
            {"option1": "S", "price": "89.00", "inventory_quantity": 30},
            {"option1": "M", "price": "89.00", "inventory_quantity": 30},
            {"option1": "L", "price": "89.00", "inventory_quantity": 30},
        ],
    },
    {
        "title": "Wool Hiking Socks",
        "body_html": "Merino wool hiking socks with extra heel and toe padding.",
        "vendor": "SockCo", "product_type": "Socks",
        "tags": "socks, hiking, wool, merino, outdoor, clothing",
        "options": [{"name": "Size"}],
        "variants": [
            {"option1": "M", "price": "149.00", "inventory_quantity": 20},
            {"option1": "L", "price": "149.00", "inventory_quantity": 20},
        ],
    },
    {
        "title": "Compression Running Socks",
        "body_html": "Performance compression socks for runners.",
        "vendor": "SockCo", "product_type": "Socks",
        "tags": "socks, compression, running, sport, clothing",
        "options": [{"name": "Size"}],
        "variants": [
            {"option1": "S/M", "price": "129.00", "inventory_quantity": 25},
            {"option1": "L/XL", "price": "129.00", "inventory_quantity": 25},
        ],
    },
]

for p in PRODUCTS:
    resp = httpx.post(URL, json={"product": p}, headers=HEADERS, timeout=15)
    if resp.is_success:
        print(f"  ✅  {resp.json()['product']['title']}")
    else:
        print(f"  ❌  {p['title']}")
        print(f"       {resp.text}")
    time.sleep(0.5)
