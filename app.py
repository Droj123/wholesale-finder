from flask import Flask, render_template, request, jsonify
import requests
import os
from statistics import median

app = Flask(__name__)

API_KEY = os.environ.get("HASDATA_API_KEY", "")
ZILLOW_BASE = "https://api.hasdata.com/scrape/zillow"


def fetch_comps(keyword, beds_min, beds_max):
    resp = requests.get(
        f"{ZILLOW_BASE}/listing",
        params={"keyword": keyword, "type": "recentlySold", "beds[min]": beds_min, "beds[max]": beds_max},
        headers={"Content-Type": "application/json", "x-api-key": API_KEY},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def parse_comps(data):
    listings = (
        data.get("searchResults")
        or data.get("results")
        or data.get("listings")
        or []
    )
    comps = []
    for item in listings[:20]:
        raw_price = item.get("price") or item.get("unformattedPrice")
        if not raw_price:
            continue
        try:
            price = float(str(raw_price).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            continue

        sqft = item.get("livingArea") or item.get("area") or item.get("sqft")
        price_per_sqft = round(price / sqft) if sqft and sqft > 0 else None

        comps.append({
            "address": item.get("address") or item.get("streetAddress") or "",
            "price": round(price),
            "beds": item.get("beds") or item.get("bedrooms"),
            "baths": item.get("baths") or item.get("bathrooms"),
            "sqft": sqft,
            "price_per_sqft": price_per_sqft,
        })
    return comps


def calc_mao(arv, repair_costs):
    return round(arv * 0.70 - repair_costs)


def recommend_strategy(arv, mao, asking_price, repair_costs):
    if not arv:
        return "Insufficient Data", "No comparable sales found — try a broader location.", "gray"

    equity = arv - asking_price - repair_costs
    spread = mao - asking_price

    if spread <= 0:
        return (
            "Pass on This Deal",
            f"Asking price exceeds your MAO of ${mao:,.0f}. Negotiate a lower price or re-estimate repairs.",
            "red",
        )
    if repair_costs < 25000 and equity > 40000:
        return (
            "Direct Wholesale Assignment",
            f"Strong equity of ${equity:,.0f} with light repairs — ideal for a quick assignment to a cash buyer. "
            "No capital needed, fast close.",
            "green",
        )
    if repair_costs >= 25000 and equity > 40000:
        return (
            "Assign to Fix-and-Flip Investor",
            f"Great ARV upside but heavy rehab of ${repair_costs:,.0f}. Target experienced flippers who have "
            "the crews and capital to execute.",
            "green",
        )
    if equity > 15000:
        return (
            "Negotiate Down or Double Close",
            f"Moderate spread of ${equity:,.0f}. Push the seller to your MAO, or structure a double close "
            "to lock in your wholesale fee.",
            "yellow",
        )
    return (
        "Creative Finance Only",
        "Thin equity at current numbers. Explore subject-to, seller carry, or a novation agreement "
        "instead of a standard assignment.",
        "yellow",
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    address = (data.get("address") or "").strip()
    beds = int(data.get("beds") or 3)
    repair_costs = float(data.get("repair_costs") or 0)
    asking_price = float(data.get("asking_price") or 0)

    if not address:
        return jsonify({"error": "Address is required"}), 400
    if not API_KEY:
        return jsonify({"error": "HASDATA_API_KEY environment variable not set"}), 500

    try:
        raw = fetch_comps(address, beds_min=max(1, beds - 1), beds_max=beds + 1)
    except requests.RequestException as exc:
        return jsonify({"error": f"Data fetch failed: {exc}"}), 502

    comps = parse_comps(raw)
    arv = round(median([c["price"] for c in comps])) if comps else 0
    mao = calc_mao(arv, repair_costs) if arv else 0
    strategy, explanation, color = recommend_strategy(arv, mao, asking_price, repair_costs)

    return jsonify({
        "comps": comps,
        "arv": arv,
        "mao": mao,
        "equity_spread": round(arv - asking_price - repair_costs) if arv else 0,
        "strategy": strategy,
        "explanation": explanation,
        "color": color,
    })


if __name__ == "__main__":
    app.run(debug=True)
