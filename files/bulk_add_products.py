#!/usr/bin/env python3
"""
Bulk product creator for Bob's Tech Shop.
Creates 10 tech, 5 sock, and 5 meat products via the Shopify Admin API.

Run with:
  venv/bin/python3.14 bulk_add_products.py
"""

import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN")
TOKEN  = os.getenv("SHOPIFY_ADMIN_TOKEN")
URL    = f"https://{DOMAIN}/admin/api/2024-01/products.json"
HEADERS = {
    "X-Shopify-Access-Token": TOKEN,
    "Content-Type": "application/json",
}

PRODUCTS = [
    # ── Tech ──────────────────────────────────────────────────────────────────
    {
        "title": "Wireless Bluetooth Headphones",
        "body_html": "Over-ear noise-cancelling headphones with 30-hour battery life and premium sound.",
        "vendor": "SoundPro",
        "product_type": "Audio",
        "tags": "audio, headphones, wireless, bluetooth, noise-cancelling",
        "variants": [{"price": "1299.00", "inventory_quantity": 15}],
    },
    {
        "title": "Mechanical Gaming Keyboard",
        "body_html": "TKL mechanical keyboard with RGB backlight and tactile blue switches.",
        "vendor": "KeyMaster",
        "product_type": "Gaming",
        "tags": "gaming, keyboard, mechanical, rgb, peripherals",
        "variants": [{"price": "899.00", "inventory_quantity": 10}],
    },
    {
        "title": "USB-C Charging Cable 2m",
        "body_html": "Braided USB-C to USB-C fast-charging cable, supports 100W PD.",
        "vendor": "CableWorks",
        "product_type": "Cables",
        "tags": "cable, usb-c, charging, accessories",
        "variants": [{"price": "149.00", "inventory_quantity": 50}],
    },
    {
        "title": "Portable Bluetooth Speaker",
        "body_html": "Waterproof speaker with 360° sound, 12-hour battery, and built-in mic.",
        "vendor": "SoundPro",
        "product_type": "Audio",
        "tags": "audio, speaker, bluetooth, portable, waterproof",
        "variants": [{"price": "799.00", "inventory_quantity": 12}],
    },
    {
        "title": "Wireless Gaming Mouse",
        "body_html": "Lightweight wireless gaming mouse with 25,000 DPI sensor and 70-hour battery.",
        "vendor": "KeyMaster",
        "product_type": "Gaming",
        "tags": "gaming, mouse, wireless, peripherals",
        "variants": [{"price": "749.00", "inventory_quantity": 8}],
    },
    {
        "title": "27-inch 4K Monitor",
        "body_html": "IPS 4K UHD monitor with 144Hz refresh rate, HDR400, and USB-C connectivity.",
        "vendor": "ViewTech",
        "product_type": "Monitors",
        "tags": "monitor, 4k, gaming, display, tech",
        "variants": [{"price": "7999.00", "inventory_quantity": 5}],
    },
    {
        "title": "Laptop Stand Aluminium",
        "body_html": "Adjustable aluminium laptop stand, compatible with MacBooks and all 13–17 inch laptops.",
        "vendor": "DeskPro",
        "product_type": "Accessories",
        "tags": "laptop, stand, accessories, macbook, desk",
        "variants": [{"price": "499.00", "inventory_quantity": 20}],
    },
    {
        "title": "1TB Portable SSD",
        "body_html": "Pocket-sized SSD with 1050MB/s read speeds and USB-C connection. Drop-resistant.",
        "vendor": "SpeedStore",
        "product_type": "Storage",
        "tags": "storage, ssd, portable, usb-c, tech",
        "variants": [{"price": "1599.00", "inventory_quantity": 10}],
    },
    {
        "title": "Webcam 1080p HD",
        "body_html": "Full HD webcam with built-in stereo mic, auto-focus, and plug-and-play USB.",
        "vendor": "ViewTech",
        "product_type": "Accessories",
        "tags": "webcam, camera, work-from-home, accessories, tech",
        "variants": [{"price": "599.00", "inventory_quantity": 15}],
    },
    {
        "title": "Wireless Charging Pad",
        "body_html": "15W Qi wireless charging pad compatible with iPhone, Samsung, and all Qi devices.",
        "vendor": "CableWorks",
        "product_type": "Accessories",
        "tags": "charging, wireless, qi, accessories, tech",
        "variants": [{"price": "299.00", "inventory_quantity": 25}],
    },

    # ── Socks ─────────────────────────────────────────────────────────────────
    {
        "title": "Ankle Socks 3-Pack (White)",
        "body_html": "Cushioned cotton ankle socks, breathable and durable. Sizes S/M/L.",
        "vendor": "SockCo",
        "product_type": "Socks",
        "tags": "socks, ankle, white, cotton, clothing",
        "variants": [
            {"title": "S", "price": "89.00", "inventory_quantity": 30},
            {"title": "M", "price": "89.00", "inventory_quantity": 30},
            {"title": "L", "price": "89.00", "inventory_quantity": 30},
        ],
    },
    {
        "title": "Wool Hiking Socks",
        "body_html": "Merino wool hiking socks with extra heel and toe padding. Moisture-wicking.",
        "vendor": "SockCo",
        "product_type": "Socks",
        "tags": "socks, hiking, wool, merino, outdoor, clothing",
        "variants": [
            {"title": "M", "price": "149.00", "inventory_quantity": 20},
            {"title": "L", "price": "149.00", "inventory_quantity": 20},
        ],
    },
    {
        "title": "Compression Running Socks",
        "body_html": "Performance compression socks designed for runners, reduces fatigue and supports recovery.",
        "vendor": "SockCo",
        "product_type": "Socks",
        "tags": "socks, compression, running, sport, clothing",
        "variants": [
            {"title": "S/M", "price": "129.00", "inventory_quantity": 25},
            {"title": "L/XL", "price": "129.00", "inventory_quantity": 25},
        ],
    },
    {
        "title": "Bamboo Crew Socks 5-Pack",
        "body_html": "Ultra-soft bamboo fibre crew socks. Anti-bacterial, eco-friendly, and odour-resistant.",
        "vendor": "SockCo",
        "product_type": "Socks",
        "tags": "socks, bamboo, eco, crew, clothing",
        "variants": [
            {"title": "One Size", "price": "199.00", "inventory_quantity": 40},
        ],
    },
    {
        "title": "Novelty Emoji Socks",
        "body_html": "Fun emoji-print cotton socks. One size fits most. Great as a gift.",
        "vendor": "SockCo",
        "product_type": "Socks",
        "tags": "socks, novelty, emoji, gift, fun, clothing",
        "variants": [
            {"title": "One Size", "price": "69.00", "inventory_quantity": 50},
        ],
    },

    # ── Meat ──────────────────────────────────────────────────────────────────
    {
        "title": "Beef Sirloin Steak (500g)",
        "body_html": "Premium grain-fed beef sirloin, aged 21 days. Perfect for the braai.",
        "vendor": "The Butcher",
        "product_type": "Meat",
        "tags": "meat, beef, steak, sirloin, braai, fresh",
        "variants": [{"price": "189.00", "inventory_quantity": 20}],
    },
    {
        "title": "Free-Range Chicken Breast (1kg)",
        "body_html": "Boneless, skinless free-range chicken breast. No added hormones or antibiotics.",
        "vendor": "The Butcher",
        "product_type": "Meat",
        "tags": "meat, chicken, poultry, free-range, healthy",
        "variants": [{"price": "129.00", "inventory_quantity": 30}],
    },
    {
        "title": "Boerewors (1kg)",
        "body_html": "Traditional South African boerewors made with beef and pork. Hand-twisted, coarse grind.",
        "vendor": "The Butcher",
        "product_type": "Meat",
        "tags": "meat, boerewors, sausage, braai, south-african",
        "variants": [{"price": "119.00", "inventory_quantity": 25}],
    },
    {
        "title": "Lamb Chops (600g)",
        "body_html": "Tender Karoo lamb loin chops. Lightly seasoned with rosemary salt.",
        "vendor": "The Butcher",
        "product_type": "Meat",
        "tags": "meat, lamb, chops, karoo, braai",
        "variants": [{"price": "229.00", "inventory_quantity": 15}],
    },
    {
        "title": "Pork Ribs Rack",
        "body_html": "Full rack of pork ribs, slow-cook ready. Approx. 1.2kg per rack.",
        "vendor": "The Butcher",
        "product_type": "Meat",
        "tags": "meat, pork, ribs, slow-cook, braai",
        "variants": [{"price": "179.00", "inventory_quantity": 15}],
    },
]


def create_product(product: dict) -> dict:
    resp = httpx.post(URL, json={"product": product}, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()["product"]


def main():
    print(f"Creating {len(PRODUCTS)} products on {DOMAIN}...\n")
    created = []
    failed  = []

    for p in PRODUCTS:
        try:
            result = create_product(p)
            price  = p["variants"][0]["price"]
            print(f"  ✅  {result['title']:<45} R {price}")
            created.append(result)
            time.sleep(0.5)   # stay well under Shopify's rate limit
        except Exception as exc:
            print(f"  ❌  {p['title']:<45} {exc}")
            failed.append(p["title"])

    print(f"\nDone. {len(created)} created, {len(failed)} failed.")
    if failed:
        print("Failed:", failed)


if __name__ == "__main__":
    main()
