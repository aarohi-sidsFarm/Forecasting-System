import httpx

for date, label in [("2026-06-05", "TARGET")]:
    r = httpx.get(f"http://localhost:8000/api/forecast_day?date={date}", timeout=90)
    r.raise_for_status()
    d = r.json()
    print(f"\n=== {label} ({date}) ===")
    rows = d.get("product_breakdown", [])
    for row in rows:
        if row.get("city") == "HYD":
            print(
                f"  {row['product_name']}: total={row['total_quantity']:,} "
                f"subs={row.get('subscription_qty', 0):,} "
                f"known={row.get('known_buy_once_qty', 0):,} "
                f"ml_unknown={row.get('ml_unknown_adhoc_qty', 0):,} "
                f"method={row['method']}"
            )
    meta = d["meta"]
    print(
        "  META -> "
        f"subs={meta.get('subscription_qty', 0):,}  "
        f"known={meta.get('known_buy_once_qty', 0):,}  "
        f"ml_unknown={meta.get('ml_unknown_adhoc_qty', 0):,}  "
        f"total={meta.get('total_quantity', 0):,}"
    )
