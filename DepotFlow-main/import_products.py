import os
import django
import pandas as pd
import re

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from inventory.models import Product

def extract_package(text):
    text = text.upper()
    if "PET" in text:
        return "PET"
    if "RGB" in text:
        return "RGB"
    if "CAN" in text:
        return "CAN"
    return "PACK"

def extract_pack_size(text):
    match = re.search(r"X(\d+)", text.upper())
    return int(match.group(1)) if match else 1

def extract_volume(text):
    text = str(text or "").upper()
    # Prefer explicit volume units anywhere in the description, including
    # names such as "Monster 500ml X12" and "Predator 400ml X12".
    match = re.search(r"(?<![A-Z0-9.])(\d+(?:\.\d+)?)\s*(ML|CL|L)\b", text)
    if match:
        return f"{match.group(1)} {match.group(2)}"

    # Legacy NBC catalogue token: 401 PET is calculated as 0.4 litres.
    match = re.match(r"^\s*(401)(?:\s|$)", text)
    if match:
        return "0.4 L"

    # Preserve existing leading no-unit catalogue formats.
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\b", text)
    return match.group(1) if match else ""


def extract_category(text):
    text = text.upper()

    if any(x in text for x in ["COCA COLA", "COKE", "SPRITE", "FANTA"]):
        return "Carbonated Soft Drink"
    if "SCHWEPPES" in text:
        return "Mixer"
    if any(x in text for x in ["MONSTER", "PREDATOR"]):
        return "Energy Drink"
    if "FIVE ALIVE" in text:
        return "Juice"
    if "EVA WATER" in text:
        return "Water"

    return "Other"

df = pd.read_excel("products.xlsx")

count = 0

for _, row in df.iterrows():
    Product.objects.update_or_create(
        sku=str(row["sku"]).strip(),
        defaults={
            "name": str(row["description"]).strip(),
            "category": extract_category(str(row["description"])),
            "package_type": extract_package(str(row["description"])),
            "volume": extract_volume(str(row["description"])),
            "pack_size": extract_pack_size(str(row["description"])),
        },
    )
    count += 1

print(f"{count} products imported successfully.")