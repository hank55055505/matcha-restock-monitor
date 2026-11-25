
import requests
from bs4 import BeautifulSoup

url = "https://www.marukyu-koyamaen.co.jp/english/shop/products/1161020c1"

response = requests.get(
    url,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30
)

print("HTTP:", response.status_code)
print("URL:", response.url)
print("HTML length:", len(response.text))

soup = BeautifulSoup(response.text, "html.parser")

print("\n--- PAGE TITLE ---")
print(soup.title.get_text(strip=True) if soup.title else "No title")

print("\n--- PRODUCT VARIATIONS ---")
for node in soup.find_all(attrs={"data-product_variations": True}):
    print(node.get("data-product_variations"))

print("\n--- SKU / STOCK TEXT ---")
for text in soup.stripped_strings:
    if any(word in text.lower() for word in [
        "stock", "sold out", "unavailable", "1161020"
    ]):
        print(text)

print("\n--- SKU ELEMENTS ---")
for node in soup.find_all(string=lambda x: x and "1161020" in x):
    print(node.parent)
