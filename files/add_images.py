#!/usr/bin/env python3
"""
Adds stock photos to all products via the Shopify Admin API.
Images are fetched from Unsplash by Shopify's servers directly.

Run with:
  venv/bin/python3.14 add_images.py
"""

import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DOMAIN  = os.getenv("SHOPIFY_STORE_DOMAIN")
TOKEN   = os.getenv("SHOPIFY_ADMIN_TOKEN")
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

# Curated Unsplash photo IDs per product title (keyword match, lowercase)
IMAGE_MAP = {
    # ── Tech ──────────────────────────────────────────────────────────────────
    "wireless bluetooth headphones":  "photo-1505740420509-14d7da0f0aa8",
    "mechanical gaming keyboard":     "photo-1587829741301-dc798b83add3",
    "usb-c charging cable 2m":        "photo-1583863788434-e58a36330cf3",
    "portable bluetooth speaker":     "photo-1608043152269-423dbba4e7e1",
    "wireless gaming mouse":          "photo-1527814050087-3793815479db",
    "27-inch 4k monitor":             "photo-1547119957-637f8679db1e",
    "laptop stand aluminium":         "photo-1593642632559-0c6d3fc62b89",
    "1tb portable ssd":               "photo-1531492153773-0f2085893498",
    "webcam 1080p hd":                "photo-1587825140708-dfaf72ae4b04",
    "wireless charging pad":          "photo-1586953208448-b90a07a46e44",

    # ── Socks ─────────────────────────────────────────────────────────────────
    "ankle socks 3-pack (white)":     "photo-1542291026-7eec264c27ff",
    "wool hiking socks":              "photo-1544966503-7cc5b7567e7d",
    "compression running socks":      "photo-1556742049-0cfed4f6a45d",
    "bamboo crew socks 5-pack":       "photo-1560769629-975ec94e6a86",
    "novelty emoji socks":            "photo-1586350977771-b3b0abd50c82",

    # ── Meat ──────────────────────────────────────────────────────────────────
    "beef sirloin steak (500g)":      "photo-1559847844-5315695dadae",
    "free-range chicken breast (1kg)":"photo-1604503468357-46aecad4e40b",
    "boerewors (1kg)":                "photo-1555396273-d3df2c36d78f",
    "lamb chops (600g)":              "photo-1544025162-d76538bba8a8",
    "pork ribs rack":                 "photo-1544025185-04d05c8f27f4",

    # ── Existing 3 products ───────────────────────────────────────────────────
    "sock":                           "photo-1510553874272-b87a8f5dfb37",
    "macbook sleeve":                 "photo-1548036328-c9fa89d128fa",
    "iphone charger":                 "photo-1601972599748-ef4d3b954fc1",
}


def get_all_products() -> list[dict]:
    url = f"https://{DOMAIN}/admin/api/2024-01/products.json?limit=250&fields=id,title"
    resp = httpx.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()["products"]


def add_image(product_id: int, photo_id: str) -> bool:
    image_url = f"https://images.unsplash.com/{photo_id}?w=800&q=80&fit=crop"
    url  = f"https://{DOMAIN}/admin/api/2024-01/products/{product_id}/images.json"
    resp = httpx.post(url, json={"image": {"src": image_url}}, headers=HEADERS, timeout=20)
    return resp.is_success


def main():
    print("Fetching products...")
    products = get_all_products()
    print(f"Found {len(products)} products.\n")

    matched   = 0
    skipped   = 0
    succeeded = 0
    failed    = []

    for p in products:
        key = p["title"].lower()
        photo_id = IMAGE_MAP.get(key)

        if not photo_id:
            print(f"  --   {p['title']:<45} (no image mapped)")
            skipped += 1
            continue

        matched += 1
        ok = add_image(p["id"], photo_id)
        if ok:
            print(f"  ✅   {p['title']}")
            succeeded += 1
        else:
            print(f"  ❌   {p['title']}")
            failed.append(p["title"])

        time.sleep(0.4)

    print(f"\nDone. {succeeded} images added, {len(failed)} failed, {skipped} skipped.")
    if failed:
        print("Failed:", failed)


if __name__ == "__main__":
    main()
