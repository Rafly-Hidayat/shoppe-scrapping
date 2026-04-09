import os
import time
from urllib.parse import quote, urlparse

from flask import Flask, render_template, request, jsonify
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# Di VPS/cloud (Render, dll.) IP sering ditolak Shopee (error 90309999). Set proxy residential jika perlu:
# PLAYWRIGHT_PROXY=http://user:pass@host:port
_PLAYWRIGHT_PROXY = os.environ.get("PLAYWRIGHT_PROXY", "").strip()

_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    # Wajib umum di container Linux (Docker / Render)
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
]


def _proxy_for_context():
    if not _PLAYWRIGHT_PROXY:
        return None
    parsed = urlparse(_PLAYWRIGHT_PROXY)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    server = f"{parsed.scheme}://{parsed.hostname}:{port}"
    conf = {"server": server}
    if parsed.username:
        conf["username"] = parsed.username
    if parsed.password:
        conf["password"] = parsed.password
    return conf


def scrape_shopee(keyword: str, top_n: int = 3):
    """
    Load Shopee search in a real browser and capture the internal search_items JSON.
    Direct HTTP requests to this API are blocked (403 / error 90309999).
    Results are sorted by lowest price locally (API is called with relevancy by the page).
    """
    search_url = f"https://shopee.co.id/search?keyword={quote(keyword)}"
    state = {"payload": None, "risk_error": None}

    def on_response(response):
        if state["payload"] is not None:
            return
        if "search_items" not in response.url or response.status != 200:
            return
        try:
            payload = response.json()
        except Exception:
            return
        err = payload.get("error")
        if err not in (None, 0):
            if err == 90309999:
                state["risk_error"] = 90309999
            return
        items = payload.get("items") or []
        if not items:
            return
        state["payload"] = payload

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=_CHROMIUM_ARGS,
            )
            try:
                proxy = _proxy_for_context()
                context_kw = {
                    "user_agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "locale": "id-ID",
                    "timezone_id": "Asia/Jakarta",
                    "viewport": {"width": 1920, "height": 1080},
                }
                if proxy:
                    context_kw["proxy"] = proxy
                context = browser.new_context(**context_kw)
                page = context.new_page()
                page.on("response", on_response)
                page.goto(search_url, wait_until="domcontentloaded", timeout=90_000)
                deadline = time.time() + 75.0
                while time.time() < deadline and state["payload"] is None:
                    page.wait_for_timeout(400)
            finally:
                browser.close()
    except PlaywrightTimeout:
        raise RuntimeError(
            "Timeout menunggu respons Shopee. Periksa koneksi atau coba lagi."
        )
    except Exception as e:
        raise RuntimeError(f"Gagal mengambil data dari Shopee: {e}")

    data = state["payload"]
    if data is None:
        if state["risk_error"] == 90309999:
            raise RuntimeError(
                "Shopee memblokir permintaan (90309999). Server hosting sering memakai IP data center "
                "yang ditandai. Lokal biasanya aman karena IP rumah/kantor."
            )
        raise RuntimeError(
            "Tidak ada data pencarian dari Shopee. Coba lagi atau periksa keyword."
        )

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
