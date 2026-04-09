from urllib.parse import quote

from flask import Flask, render_template, request, jsonify
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

app = Flask(__name__)


def scrape_shopee(keyword: str, top_n: int = 3):
    """
    Load Shopee search in a real browser and capture the internal search_items JSON.
    Direct HTTP requests to this API are blocked (403 / error 90309999).
    Results are sorted by lowest price locally (API is called with relevancy by the page).
    """
    search_url = f"https://shopee.co.id/search?keyword={quote(keyword)}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    locale="id-ID",
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()
                with page.expect_response(
                    lambda r: "search_items" in r.url and r.status == 200,
                    timeout=90_000,
                ) as resp_info:
                    page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=90_000,
                    )
                data = resp_info.value.json()
            finally:
                browser.close()
    except PlaywrightTimeout:
        raise RuntimeError(
            "Timeout menunggu respons Shopee. Periksa koneksi atau coba lagi."
        )
    except Exception as e:
        raise RuntimeError(f"Gagal mengambil data dari Shopee: {e}")

    err = data.get("error")
    if err not in (None, 0):
        raise RuntimeError(
            f"Shopee menolak permintaan (error {err}). Coba lagi nanti."
        )

    items = data.get("items") or []
    if not items:
        return []

    products = []
    for item in items:
        basic = item.get("item_basic") or item
        name = basic.get("name", "")
        raw_price = basic.get("price", 0)
        price = raw_price / 100000
        shop_name = basic.get("shop_name", "")
        item_id = basic.get("itemid", "")
        shop_id = basic.get("shopid", "")

        slug = name.lower().replace(" ", "-")[:60]
        link = f"https://shopee.co.id/{quote(shop_name)}/{slug}-i.{shop_id}.{item_id}"

        if price > 0 and name:
            products.append({
                "name": name,
                "price": price,
                "price_formatted": f"Rp {int(price):,}".replace(",", "."),
                "link": link,
            })

    products.sort(key=lambda x: x["price"])
    return products[:top_n]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    keyword = request.json.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "Keyword tidak boleh kosong."}), 400

    try:
        results = scrape_shopee(keyword)
        if not results:
            return jsonify({"error": "Produk tidak ditemukan untuk keyword tersebut."}), 404
        return jsonify({"keyword": keyword, "results": results})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
