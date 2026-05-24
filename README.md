# DealFlow — Wholesale Deal Analyzer

Enter any address to pull recent comparable sales, calculate ARV and MAO using the 70% rule, and get a wholesale strategy recommendation.

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your Hasdata API key
cp .env.example .env
# Edit .env and paste your key

# 4. Run the app
python app.py
```

Open http://localhost:5000 in your browser.

## How It Works

| Term | Definition |
|------|------------|
| **ARV** | After Repair Value — median of recent comparable sales in the area |
| **MAO** | Maximum Allowable Offer — `ARV × 70% − Repair Costs` |
| **Spread** | `ARV − Asking Price − Repair Costs` — your equity cushion |

### Strategy Logic

| Condition | Recommendation |
|-----------|---------------|
| Asking > MAO | Pass — negotiate or move on |
| Low repairs + high spread | Direct wholesale assignment |
| High repairs + high spread | Assign to fix-and-flip investor |
| Moderate spread | Negotiate down or double close |
| Thin spread | Creative finance (subject-to, seller carry) |

## Data Source

Comparable sales are pulled from Zillow via the [Hasdata API](https://hasdata.com).
