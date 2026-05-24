from flask import Flask, render_template, request, jsonify
import requests
import os
from statistics import median

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
API_KEY = os.environ.get("HASDATA_API_KEY", "")
ZILLOW_BASE = "https://api.hasdata.com/scrape/zillow"


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_comps(keyword, beds_min, beds_max):
    resp = requests.get(
        f"{ZILLOW_BASE}/listing",
        params={
            "keyword": keyword,
            "type": "recentlySold",
            "beds[min]": beds_min,
            "beds[max]": beds_max,
        },
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
        raw = item.get("price") or item.get("unformattedPrice")
        if not raw:
            continue
        try:
            price = float(str(raw).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            continue
        if price < 10_000:
            continue
        sqft = item.get("livingArea") or item.get("area") or item.get("sqft")
        ppsf = round(price / sqft) if sqft and sqft > 0 else None
        comps.append({
            "address": item.get("address") or item.get("streetAddress") or "",
            "price": round(price),
            "beds": item.get("beds") or item.get("bedrooms"),
            "baths": item.get("baths") or item.get("bathrooms"),
            "sqft": sqft,
            "price_per_sqft": ppsf,
        })
    return comps


# ── Calculations ──────────────────────────────────────────────────────────────

def _pct(values, p):
    """Return the value at percentile p (0-100) using linear interpolation."""
    s = sorted(values)
    idx = p / 100 * (len(s) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (idx - lo))


def arv_scenarios(comps):
    """Conservative (25th pct), Likely (median), Aggressive (75th pct)."""
    if not comps:
        return 0, 0, 0
    prices = [c["price"] for c in comps]
    return _pct(prices, 25), round(median(prices)), _pct(prices, 75)


def offer_tiers(likely_arv, cons_arv, repairs, fee):
    """
    Buyer MAO  = Likely ARV × 70% − Repairs   (what a cash buyer will pay)
    Max Offer  = Buyer MAO − 2/3 of fee        (thin but doable)
    Target     = Buyer MAO − fee               (hit your goal)
    Safe       = Conservative ARV × 65% − Repairs − fee  (worst-case)
    """
    buyer_mao    = round(likely_arv * 0.70 - repairs)
    max_offer    = round(buyer_mao - fee * 0.67)
    target_offer = round(buyer_mao - fee)
    safe_offer   = round(cons_arv  * 0.65 - repairs - fee)
    return buyer_mao, max_offer, target_offer, safe_offer


def median_ppsf(comps):
    vals = [c["price_per_sqft"] for c in comps if c.get("price_per_sqft")]
    return round(median(vals)) if vals else None


# ── Intelligence layers ───────────────────────────────────────────────────────

def build_risk_flags(comps, cons_arv, likely_arv, asking, repairs, buyer_mao):
    flags = []
    n = len(comps)

    if n < 3:
        flags.append(
            f"Only {n} comp{'s' if n != 1 else ''} found — ARV confidence is low. Verify manually."
        )
    if n >= 2 and likely_arv:
        prices = [c["price"] for c in comps]
        variance = (max(prices) - min(prices)) / likely_arv
        if variance > 0.40:
            flags.append(
                f"Comp prices vary by {variance:.0%} — inconsistent market. Lean on conservative ARV."
            )
    if likely_arv and repairs > likely_arv * 0.30:
        flags.append(
            f"Repairs (${repairs:,.0f}) exceed 30% of ARV — heavy rehab risk. Get contractor bids first."
        )
    if asking and buyer_mao and asking >= buyer_mao:
        flags.append(
            f"Asking price (${asking:,.0f}) ≥ Buyer MAO (${buyer_mao:,.0f}) — no room for your wholesale fee."
        )
    if likely_arv and asking and (asking + repairs) / likely_arv > 0.85:
        pct = (asking + repairs) / likely_arv
        flags.append(f"All-in cost is {pct:.0%} of ARV — thin margin for your buyer.")
    if repairs == 0:
        flags.append("No repair estimate entered — MAO may be overstated. Always add a repair budget.")

    return flags


def build_seller_questions(repairs):
    questions = [
        "Why are you selling, and what's your ideal closing timeline?",
        "Is there a mortgage on the property? Approximate payoff balance?",
        "Any liens, back taxes, or code violations we should know about?",
        "Has it been listed on MLS before? If so, why didn't it sell?",
        "What's the condition of the roof, HVAC, and foundation?",
        "Are there any tenants currently in the property?",
        "Are you open to a quick cash close if the price works for both of us?",
    ]
    if repairs > 40_000:
        questions.insert(2, "Have you already received any contractor bids for repairs?")
    return questions


def build_buyer_pitch(address, beds, baths, likely_arv, cons_arv, buyer_mao, repairs):
    size   = f"{beds}bd/{baths}ba" if beds and baths else f"{beds}bd" if beds else ""
    style  = "fix-and-flip" if repairs > 20_000 else "turn-key flip or BRRRR"
    return (
        f"{size} in {address}. ARV ${likely_arv:,.0f} "
        f"(conservative ${cons_arv:,.0f}). Repairs est. ${repairs:,.0f}. "
        f"Buyer MAO ${buyer_mao:,.0f}. Strong {style} play. "
        f"Assignment contract available — DM for details."
    )


def strategy_rec(likely_arv, buyer_mao, asking, repairs):
    if not likely_arv:
        return "Insufficient Data", "No comps found. Try a broader location or add city/zip.", "gray"
    equity = likely_arv - asking - repairs
    spread = buyer_mao - asking
    if spread <= 0:
        return (
            "Pass on This Deal",
            f"Asking price exceeds buyer MAO of ${buyer_mao:,.0f}. Negotiate down or walk.",
            "red",
        )
    if repairs < 25_000 and equity > 40_000:
        return (
            "Direct Wholesale Assignment",
            f"${equity:,.0f} equity with light repairs — quick assignment to a cash buyer. No capital needed.",
            "green",
        )
    if repairs >= 25_000 and equity > 40_000:
        return (
            "Assign to Fix-and-Flip Investor",
            f"Strong upside but heavy rehab (${repairs:,.0f}). Target experienced flippers with crews.",
            "green",
        )
    if equity > 15_000:
        return (
            "Negotiate Down or Double Close",
            f"Moderate ${equity:,.0f} spread. Push seller to your MAO or structure a double close.",
            "yellow",
        )
    return (
        "Creative Finance Only",
        "Thin equity at current numbers. Explore subject-to, seller carry, or novation agreement.",
        "yellow",
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    d       = request.get_json()
    address = (d.get("address") or "").strip()
    beds    = int(d.get("beds") or 3)
    baths   = d.get("baths")
    repairs = float(d.get("repair_costs") or 0)
    asking  = float(d.get("asking_price") or 0)
    rent    = float(d.get("monthly_rent") or 0)
    fee     = float(d.get("wholesale_fee") or 15_000)

    if not address:
        return jsonify({"error": "Address is required"}), 400
    if not API_KEY:
        return jsonify({"error": "HASDATA_API_KEY not configured — check your .env file"}), 500

    try:
        raw = fetch_comps(address, max(1, beds - 1), beds + 1)
    except requests.RequestException as exc:
        return jsonify({"error": f"Data fetch failed: {exc}"}), 502

    comps                             = parse_comps(raw)
    cons_arv, likely_arv, agg_arv    = arv_scenarios(comps)
    buyer_mao, max_off, target, safe  = offer_tiers(likely_arv, cons_arv, repairs, fee)
    ppsf                              = median_ppsf(comps)

    all_in_cap  = round((asking + repairs) / likely_arv * 100, 1) if likely_arv else None
    rent_to_arv = round(rent / likely_arv * 100, 2) if likely_arv and rent else None
    rent_to_mao = round(rent / max_off * 100, 2) if max_off and max_off > 0 and rent else None

    strategy, explanation, color = strategy_rec(likely_arv, buyer_mao, asking, repairs)

    return jsonify({
        # Comps
        "comps":          comps,
        "compCount":      len(comps),
        "medianPpsf":     ppsf,
        "allInCap":       all_in_cap,
        # ARV scenarios
        "conservativeArv": cons_arv,
        "likelyArv":       likely_arv,
        "aggressiveArv":   agg_arv,
        # Offer tiers
        "buyerMao":    buyer_mao,
        "maxOffer":    max_off,
        "targetOffer": target,
        "safeOffer":   safe,
        # Rental
        "rentToArv": rent_to_arv,
        "rentToMao": rent_to_mao,
        # Intelligence
        "riskFlags":       build_risk_flags(comps, cons_arv, likely_arv, asking, repairs, buyer_mao),
        "sellerQuestions": build_seller_questions(repairs),
        "buyerPitch":      build_buyer_pitch(address, beds, baths, likely_arv, cons_arv, buyer_mao, repairs),
        "strategy":        strategy,
        "explanation":     explanation,
        "color":           color,
        # Echo inputs for CSV
        "askingPrice": asking,
        "repairs":     repairs,
    })


if __name__ == "__main__":
    app.run(debug=True)
