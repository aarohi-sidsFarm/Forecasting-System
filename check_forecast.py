import requests

for date, label in [("2026-05-19", "TODAY"), ("2026-05-20", "TOMORROW")]:
    r = requests.get(f"http://localhost:8000/api/forecast_day?date={date}", timeout=90)
    d = r.json()
    print(f"\n=== {label} ({date}) ===")
    # Show ALL rows for A2 Buffalo HYD (sub + lgbm separately)
    rows = d.get("product_breakdown", [])
    for row in rows:
        if row.get("city") == "HYD":
            print(f"  {row['product_name']}: {row['total_quantity']:,}  method={row['method']}")
    print(f"  META -> sub_qty={d['meta'].get('subscription_qty'):,}  ml_qty={d['meta'].get('ml_qty'):,}  total={d['meta'].get('total_quantity'):,}")
