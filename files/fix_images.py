#!/usr/bin/env python3
"""Retries failed images with alternative Unsplash photo IDs."""
import os, time, httpx
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DOMAIN  = os.getenv("SHOPIFY_STORE_DOMAIN")
TOKEN   = os.getenv("SHOPIFY_ADMIN_TOKEN")
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

RETRY_MAP = {
    "1tb portable ssd":                "photo-1558494949-ef010cbdcc31",
    "boerewors (1kg)":                 "photo-1619518943792-56b36dbe7a83",
    "free-range chicken breast (1kg)": "photo-1598170845058-32b9d6a5da37",
    "iphone charger":                  "photo-1558618666-fcd25c85cd64",
    "lamb chops (600g)":               "photo-1529692236671-f1f6cf9683ba",
    "pork ribs rack":                  "photo-1565557623262-b51c2513a641",
    "sock":                            "photo-1434494878577-86c23bcb06b9",
    "usb-c charging cable 2m":         "photo-1601972599748-ef4d3b954fc1",
    "wireless bluetooth headphones":   "photo-1484704849700-f032a568e944",
    "wireless charging pad":           "photo-1609091839311-d5365f9ff1c5",
    "wool hiking socks":               "photo-1592194996308-7b43878e84a6",
}

def get_products_needing_images() -> list[dict]:
    """Return products that currently have no images — skip duplicates already done."""
    url = f"https://{DOMAIN}/admin/api/2024-01/products.json?limit=250&fields=id,title,images"
    resp = httpx.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    products = resp.json()["products"]
    # Only target products with no images that are in our retry map
    return [p for p in products if not p["images"] and p["title"].lower() in RETRY_MAP]

def add_image(product_id: int, photo_id: str) -> bool:
    src  = f"https://images.unsplash.com/{photo_id}?w=800&q=80&fit=crop"
    url  = f"https://{DOMAIN}/admin/api/2024-01/products/{product_id}/images.json"
    resp = httpx.post(url, json={"image": {"src": src}}, headers=HEADERS, timeout=20)
    return resp.is_success

def main():
    print("Finding products without images...")
    targets = get_products_needing_images()
    print(f"{len(targets)} products to fix.\n")

    for p in targets:
        photo_id = RETRY_MAP[p["title"].lower()]
        ok = add_image(p["id"], photo_id)
        status = "✅" if ok else "❌"
        print(f"  {status}   {p['title']}")
        time.sleep(0.4)

if __name__ == "__main__":
    main()
