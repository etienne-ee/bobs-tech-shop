#!/usr/bin/env python3
"""Removes duplicate products, keeping the one with an image where possible."""
import os, time, httpx
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

DOMAIN  = os.getenv("SHOPIFY_STORE_DOMAIN")
TOKEN   = os.getenv("SHOPIFY_ADMIN_TOKEN")
HEADERS = {"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"}

def get_all_products():
    url = f"https://{DOMAIN}/admin/api/2024-01/products.json?limit=250&fields=id,title,images,created_at"
    resp = httpx.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()["products"]

def delete_product(product_id: int) -> bool:
    url  = f"https://{DOMAIN}/admin/api/2024-01/products/{product_id}.json"
    resp = httpx.delete(url, headers=HEADERS, timeout=15)
    return resp.is_success

def main():
    products = get_all_products()
    print(f"Found {len(products)} products total.\n")

    # Group by lowercase title
    by_title = defaultdict(list)
    for p in products:
        by_title[p["title"].lower()].append(p)

    to_delete = []
    for title, group in by_title.items():
        if len(group) == 1:
            continue
        # Keep the one with an image; if tied, keep the oldest (first created)
        group.sort(key=lambda p: (len(p["images"]) == 0, p["created_at"]))
        keeper = group[0]
        dupes  = group[1:]
        print(f"  Keeping  → {keeper['title']} (id {keeper['id']}, {'has image' if keeper['images'] else 'no image'})")
        for d in dupes:
            print(f"  Deleting → id {d['id']} ({'has image' if d['images'] else 'no image'})")
            to_delete.append(d)

    print(f"\nDeleting {len(to_delete)} duplicates...\n")
    deleted = 0
    for p in to_delete:
        ok = delete_product(p["id"])
        print(f"  {'✅' if ok else '❌'}   deleted {p['title']} (id {p['id']})")
        if ok:
            deleted += 1
        time.sleep(0.4)

    print(f"\nDone. {deleted} duplicates removed. {len(products) - deleted} products remain.")

if __name__ == "__main__":
    main()
