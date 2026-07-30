# Festival Impact Report

This report estimates festival impact from exported Redash demand windows.

Baseline uses the median quantity from days at least four days away from the festival within the exported window.

Data quality note: old exports without `festival_date` use an approximated window midpoint. Future Redash exports should include exact `festival_date` and `days_from_festival`.

Only recommendations with at least two observed years should be used for guardrails.

## HYD High-Impact Recommendations

| festival_name | city_cd | product_name | observed_years | recommended_peak_offset | recommended_peak_uplift_pct | median_baseline_qty | recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Akshaya Tritiya | HYD | A2 Buffalo Milk | 3 | -5 | 4.09 | 13930.0 | Consider festival uplift guardrail |
| Akshaya Tritiya | HYD | A2 Desi Cow Milk | 3 | -5 | 5.05 | 1337.5 | Consider festival uplift guardrail |
| Akshaya Tritiya | HYD | Cow Milk | 3 | -5 | 4.11 | 7963.5 | Consider festival uplift guardrail |
| Akshaya Tritiya | HYD | Curd | 3 | -2 | 7.61 | 1438.0 | Consider festival uplift guardrail |
| Diwali | HYD | A2 Buffalo Milk | 2 | 0 | 4.93 | 15229.5 | Consider festival uplift guardrail |
| Diwali | HYD | A2 Desi Cow Milk | 2 | 5 | 12.35 | 1492.0 | Consider festival uplift guardrail |
| Diwali | HYD | Cow Milk | 2 | 5 | 12.32 | 8906.5 | Consider festival uplift guardrail |
| Diwali | HYD | Curd | 2 | 0 | 127.93 | 1092.5 | Consider festival uplift guardrail |
| Diwali | HYD | Double Toned A2 Buffalo Milk | 2 | 0 | 4.94 | 5649.0 | Consider festival uplift guardrail |
| Dussehra | HYD | A2 Buffalo Milk | 2 | 6 | 10.32 | 13627.75 | Consider festival uplift guardrail |
| Dussehra | HYD | A2 Desi Cow Milk | 2 | 6 | 7.73 | 1385.0 | Consider festival uplift guardrail |
| Dussehra | HYD | Cow Milk | 2 | 7 | 7.04 | 8296.5 | Consider festival uplift guardrail |
| Dussehra | HYD | Curd | 2 | 7 | 74.94 | 1015.75 | Consider festival uplift guardrail |
| Dussehra | HYD | Double Toned A2 Buffalo Milk | 2 | 7 | 8.26 | 5111.25 | Consider festival uplift guardrail |
| Dussehra | HYD | Skim Milk | 2 | 7 | 9.26 | 2253.5 | Consider festival uplift guardrail |
| Ganesh Chaturthi | HYD | A2 Buffalo Milk | 2 | 0 | 15.94 | 15005.75 | Consider festival uplift guardrail |
| Ganesh Chaturthi | HYD | A2 Desi Cow Milk | 2 | 0 | 31.2 | 1477.5 | Consider festival uplift guardrail |
| Ganesh Chaturthi | HYD | Cow Milk | 2 | 0 | 25.94 | 8837.5 | Consider festival uplift guardrail |
| Ganesh Chaturthi | HYD | Curd | 2 | 0 | 103.88 | 1188.25 | Consider festival uplift guardrail |
| Ganesh Chaturthi | HYD | Double Toned A2 Buffalo Milk | 2 | 0 | 14.92 | 5527.25 | Consider festival uplift guardrail |
| Ganesh Chaturthi | HYD | Skim Milk | 2 | 0 | 9.59 | 2381.5 | Consider festival uplift guardrail |
| Hanuman Jayanti | HYD | A2 Desi Cow Milk | 3 | -6 | 7.52 | 1445.5 | Consider festival uplift guardrail |
| Hanuman Jayanti | HYD | Cow Milk | 3 | -6 | 3.96 | 8707.0 | Consider festival uplift guardrail |
| Hanuman Jayanti | HYD | Curd | 3 | 7 | 9.07 | 1350.5 | Consider festival uplift guardrail |
| Holi | HYD | A2 Desi Cow Milk | 3 | -4 | 3.27 | 1465.5 | Consider festival uplift guardrail |
| Holi | HYD | Curd | 3 | -6 | 5.07 | 1195.0 | Consider festival uplift guardrail |
| Holi | HYD | Skim Milk | 3 | 7 | 3.59 | 2249.0 | Consider festival uplift guardrail |
| Maha Shivaratri | HYD | A2 Buffalo Milk | 3 | 0 | 4.04 | 14934.0 | Consider festival uplift guardrail |
| Maha Shivaratri | HYD | A2 Desi Cow Milk | 3 | 0 | 32.95 | 1490.0 | Consider festival uplift guardrail |
| Maha Shivaratri | HYD | Cow Milk | 3 | 0 | 19.64 | 8841.0 | Consider festival uplift guardrail |
| Maha Shivaratri | HYD | Curd | 3 | -3 | 104.46 | 1207.5 | Consider festival uplift guardrail |
| Naga Panchami | HYD | A2 Desi Cow Milk | 2 | 7 | 9.07 | 1510.75 | Consider festival uplift guardrail |
| Naga Panchami | HYD | Cow Milk | 3 | 0 | 5.95 | 9273.0 | Consider festival uplift guardrail |
| Naga Panchami | HYD | Curd | 2 | 7 | 70.12 | 1112.0 | Consider festival uplift guardrail |
| Naga Panchami | HYD | Skim Milk | 3 | 0 | 4.12 | 2307.5 | Consider festival uplift guardrail |
| Nagula Chavithi | HYD | A2 Buffalo Milk | 2 | -5 | 5.43 | 15162.5 | Consider festival uplift guardrail |
| Nagula Chavithi | HYD | A2 Desi Cow Milk | 2 | 0 | 9.64 | 1528.75 | Consider festival uplift guardrail |
| Nagula Chavithi | HYD | Cow Milk | 2 | 0 | 12.3 | 8908.75 | Consider festival uplift guardrail |
| Nagula Chavithi | HYD | Curd | 2 | -5 | 91.41 | 1224.5 | Consider festival uplift guardrail |
| Nagula Chavithi | HYD | Double Toned A2 Buffalo Milk | 2 | -5 | 5.14 | 5638.0 | Consider festival uplift guardrail |

## All Recommendations

| festival_name | city_cd | product_name | observed_years | recommended_peak_offset | recommended_peak_uplift_pct | median_baseline_qty | recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Akshaya Tritiya | BLR | A2 Buffalo Milk | 3 | -3 | 6.01 | 1790.5 | Consider festival uplift guardrail |
| Akshaya Tritiya | BLR | A2 Desi Cow Milk | 3 | -6 | 5.23 | 344.0 | Consider festival uplift guardrail |
| Akshaya Tritiya | BLR | Cow Milk | 3 | -6 | 5.65 | 1652.0 | Consider festival uplift guardrail |
| Akshaya Tritiya | BLR | Curd | 3 | -2 | 15.62 | 192.5 | Consider festival uplift guardrail |
| Akshaya Tritiya | BLR | Double Toned A2 Buffalo Milk | 3 | -2 | 3.7 | 429.5 | Consider festival uplift guardrail |
| Akshaya Tritiya | BLR | Skim Milk | 3 | 7 | 5.83 | 381.5 | Consider festival uplift guardrail |
| Akshaya Tritiya | BLR | Toned Milk | 1 | 1 | 7.44 | 463.5 | Use caution: only one observed year |
| Diwali | BLR | A2 Buffalo Milk | 2 | -7 | 3.22 | 1735.0 | Consider festival uplift guardrail |
| Diwali | BLR | A2 Desi Cow Milk | 2 | 7 | 11.84 | 369.75 | Consider festival uplift guardrail |
| Diwali | BLR | Cow Milk | 2 | -6 | 1.58 | 1850.5 | No manual adjustment recommended |
| Diwali | BLR | Curd | 2 | 0 | 26.76 | 211.0 | Consider festival uplift guardrail |
| Diwali | BLR | Double Toned A2 Buffalo Milk | 2 | -6 | 4.61 | 412.25 | Consider festival uplift guardrail |
| Diwali | BLR | Skim Milk | 2 | -7 | 7.62 | 342.75 | Consider festival uplift guardrail |
| Diwali | BLR | Toned Milk | 1 | 6 | 5.64 | 195.0 | Use caution: only one observed year |
| Diwali Laxmi Puja | BLR | A2 Buffalo Milk | 1 | 7 | 4.46 | 1333.5 | Use caution: only one observed year |
| Diwali Laxmi Puja | BLR | A2 Desi Cow Milk | 1 | 6 | 9.98 | 285.5 | Use caution: only one observed year |
| Diwali Laxmi Puja | BLR | Cow Milk | 1 | 6 | 2.97 | 1719.0 | Use caution: only one observed year |
| Diwali Laxmi Puja | BLR | Curd | 1 | -2 | 73.23 | 127.0 | Use caution: only one observed year |
| Diwali Laxmi Puja | BLR | Double Toned A2 Buffalo Milk | 1 | 5 | 5.2 | 327.0 | Use caution: only one observed year |
| Diwali Laxmi Puja | BLR | Skim Milk | 1 | -7 | 13.28 | 184.5 | Use caution: only one observed year |
| Dussehra | BLR | A2 Buffalo Milk | 2 | 7 | 10.88 | 1561.5 | Consider festival uplift guardrail |
| Dussehra | BLR | A2 Desi Cow Milk | 2 | 4 | 5.91 | 375.25 | Consider festival uplift guardrail |
| Dussehra | BLR | Cow Milk | 2 | 6 | 5.74 | 1815.25 | Consider festival uplift guardrail |
| Dussehra | BLR | Curd | 2 | 7 | 23.32 | 222.75 | Consider festival uplift guardrail |
| Dussehra | BLR | Double Toned A2 Buffalo Milk | 2 | 6 | 12.28 | 391.25 | Consider festival uplift guardrail |
| Dussehra | BLR | Skim Milk | 2 | 6 | 8.4 | 352.75 | Consider festival uplift guardrail |
| Dussehra | BLR | Toned Milk | 1 | 6 | 15.93 | 191.5 | Use caution: only one observed year |
| Ganesh Chaturthi | BLR | A2 Buffalo Milk | 2 | 0 | 8.22 | 1674.75 | Consider festival uplift guardrail |
| Ganesh Chaturthi | BLR | A2 Desi Cow Milk | 2 | 5 | 2.89 | 417.25 | No manual adjustment recommended |
| Ganesh Chaturthi | BLR | Cow Milk | 2 | 0 | 5.05 | 1856.0 | Consider festival uplift guardrail |
| Ganesh Chaturthi | BLR | Curd | 2 | 0 | 31.78 | 182.0 | Consider festival uplift guardrail |
| Ganesh Chaturthi | BLR | Double Toned A2 Buffalo Milk | 2 | 7 | 5.75 | 409.75 | Consider festival uplift guardrail |
| Ganesh Chaturthi | BLR | Skim Milk | 2 | -3 | 4.9 | 352.0 | Consider festival uplift guardrail |
| Ganesh Chaturthi | BLR | Toned Milk | 1 | 7 | 15.01 | 176.5 | Use caution: only one observed year |
| Hanuman Jayanti | BLR | A2 Buffalo Milk | 3 | -6 | 7.24 | 1811.0 | Consider festival uplift guardrail |
| Hanuman Jayanti | BLR | A2 Desi Cow Milk | 3 | -1 | 5.87 | 337.5 | Consider festival uplift guardrail |
| Hanuman Jayanti | BLR | Cow Milk | 3 | -6 | 3.67 | 1856.0 | Consider festival uplift guardrail |
| Hanuman Jayanti | BLR | Curd | 3 | 5 | 3.26 | 199.5 | Consider festival uplift guardrail |
| Hanuman Jayanti | BLR | Double Toned A2 Buffalo Milk | 3 | -6 | 2.73 | 409.0 | No manual adjustment recommended |
| Hanuman Jayanti | BLR | Skim Milk | 3 | -3 | 4.26 | 376.0 | Consider festival uplift guardrail |
| Hanuman Jayanti | BLR | Toned Milk | 1 | -1 | 6.88 | 501.5 | Use caution: only one observed year |
| Holi | BLR | A2 Buffalo Milk | 3 | -6 | 4.76 | 2071.5 | Consider festival uplift guardrail |
| Holi | BLR | A2 Desi Cow Milk | 3 | -6 | 5.1 | 345.5 | Consider festival uplift guardrail |
| Holi | BLR | Cow Milk | 3 | -3 | 4.52 | 2135.5 | Consider festival uplift guardrail |
| Holi | BLR | Curd | 3 | 2 | 10.11 | 188.5 | Consider festival uplift guardrail |
| Holi | BLR | Double Toned A2 Buffalo Milk | 3 | 4 | 5.19 | 478.5 | Consider festival uplift guardrail |
| Holi | BLR | Skim Milk | 3 | -5 | 4.0 | 417.0 | Consider festival uplift guardrail |
| Holi | BLR | Toned Milk | 1 | 1 | 6.04 | 497.0 | Use caution: only one observed year |
| Maha Shivaratri | BLR | A2 Buffalo Milk | 3 | 0 | 7.72 | 1943.0 | Consider festival uplift guardrail |
| Maha Shivaratri | BLR | A2 Desi Cow Milk | 3 | 1 | 4.78 | 331.5 | Consider festival uplift guardrail |
| Maha Shivaratri | BLR | Cow Milk | 3 | 0 | 9.4 | 2242.0 | Consider festival uplift guardrail |
| Maha Shivaratri | BLR | Curd | 3 | -3 | 43.16 | 190.5 | Consider festival uplift guardrail |
| Maha Shivaratri | BLR | Double Toned A2 Buffalo Milk | 3 | 0 | 5.37 | 440.5 | Consider festival uplift guardrail |
| Maha Shivaratri | BLR | Skim Milk | 3 | 5 | 5.94 | 380.5 | Consider festival uplift guardrail |
| Maha Shivaratri | BLR | Toned Milk | 1 | 1 | 10.65 | 483.5 | Use caution: only one observed year |
| Naga Panchami | BLR | A2 Buffalo Milk | 3 | -6 | 5.91 | 2190.5 | Consider festival uplift guardrail |
| Naga Panchami | BLR | A2 Desi Cow Milk | 2 | 3 | 8.86 | 369.25 | Consider festival uplift guardrail |
| Naga Panchami | BLR | Cow Milk | 3 | -5 | 5.31 | 1800.0 | Consider festival uplift guardrail |
| Naga Panchami | BLR | Curd | 2 | 6 | 30.15 | 156.75 | Consider festival uplift guardrail |
| Naga Panchami | BLR | Double Toned A2 Buffalo Milk | 3 | 0 | 6.41 | 482.0 | Consider festival uplift guardrail |
| Naga Panchami | BLR | Skim Milk | 2 | 3 | 3.38 | 352.5 | Consider festival uplift guardrail |
| Naga Panchami | BLR | Toned Milk | 1 | 2 | 19.15 | 141.0 | Use caution: only one observed year |
| Nagula Chavithi | BLR | A2 Buffalo Milk | 2 | 6 | 5.74 | 1715.75 | Consider festival uplift guardrail |
| Nagula Chavithi | BLR | A2 Desi Cow Milk | 2 | 2 | 10.17 | 375.25 | Consider festival uplift guardrail |
| Nagula Chavithi | BLR | Cow Milk | 2 | 7 | 7.64 | 1780.75 | Consider festival uplift guardrail |
| Nagula Chavithi | BLR | Curd | 2 | 4 | 45.64 | 214.0 | Consider festival uplift guardrail |
| Nagula Chavithi | BLR | Double Toned A2 Buffalo Milk | 2 | 3 | 8.2 | 398.0 | Consider festival uplift guardrail |
| Nagula Chavithi | BLR | Skim Milk | 2 | 6 | 11.48 | 343.25 | Consider festival uplift guardrail |
| Nagula Chavithi | BLR | Toned Milk | 1 | 7 | 10.89 | 202.0 | Use caution: only one observed year |
| Ram Navami | BLR | A2 Buffalo Milk | 3 | -7 | 8.07 | 1834.0 | Consider festival uplift guardrail |
| Ram Navami | BLR | A2 Desi Cow Milk | 3 | 5 | 8.25 | 333.5 | Consider festival uplift guardrail |
| Ram Navami | BLR | Cow Milk | 3 | -1 | 6.56 | 1891.0 | Consider festival uplift guardrail |
| Ram Navami | BLR | Curd | 3 | 1 | 18.6 | 172.0 | Consider festival uplift guardrail |
| Ram Navami | BLR | Double Toned A2 Buffalo Milk | 3 | -1 | 6.88 | 416.5 | Consider festival uplift guardrail |
| Ram Navami | BLR | Skim Milk | 3 | -1 | 8.27 | 401.0 | Consider festival uplift guardrail |
| Ram Navami | BLR | Toned Milk | 1 | -7 | 9.84 | 498.0 | Use caution: only one observed year |
| Ratha Saptami | BLR | A2 Buffalo Milk | 3 | 5 | 2.5 | 1770.5 | No manual adjustment recommended |
| Ratha Saptami | BLR | A2 Desi Cow Milk | 3 | 0 | 4.64 | 323.0 | Consider festival uplift guardrail |
| Ratha Saptami | BLR | Cow Milk | 3 | 5 | 3.56 | 2192.0 | Consider festival uplift guardrail |
| Ratha Saptami | BLR | Curd | 3 | 5 | 26.96 | 172.5 | Consider festival uplift guardrail |

## Summary Sample

| delivery_year | festival_name | city_cd | product_name | window_days | avg_daily_quantity | median_daily_quantity | baseline_qty | avg_uplift_pct | max_uplift_pct | min_uplift_pct | window_total_quantity | peak_delivery_date | peak_days_from_festival | peak_daily_quantity | peak_uplift_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | Akshaya Tritiya | BLR | A2 Buffalo Milk | 15 | 720.0 | 732.0 | 732.0 | -1.64 | 6.01 | -14.48 | 10800.0 | 2024-07-05 00:00:00 | -3 | 776.0 | 6.01 |
| 2024 | Akshaya Tritiya | BLR | A2 Desi Cow Milk | 15 | 156.6 | 153.0 | 152.5 | 2.69 | 18.69 | -8.2 | 2349.0 | 2024-11-05 00:00:00 | 1 | 181.0 | 18.69 |
| 2024 | Akshaya Tritiya | BLR | Cow Milk | 15 | 676.2 | 668.0 | 678.0 | -0.27 | 23.89 | -19.91 | 10143.0 | 2024-05-16 00:00:00 | 6 | 840.0 | 23.89 |
| 2024 | Akshaya Tritiya | BLR | Curd | 15 | 62.6 | 63.0 | 64.0 | -2.19 | 28.12 | -18.75 | 939.0 | 2024-03-05 00:00:00 | -7 | 82.0 | 28.12 |
| 2024 | Akshaya Tritiya | BLR | Double Toned A2 Buffalo Milk | 15 | 211.07 | 216.0 | 216.0 | -2.28 | 11.57 | -18.52 | 3166.0 | 2024-09-05 00:00:00 | -1 | 241.0 | 11.57 |
| 2024 | Akshaya Tritiya | BLR | Skim Milk | 15 | 103.0 | 102.0 | 103.0 | -0.0 | 14.56 | -20.39 | 1545.0 | 2024-05-16 00:00:00 | 6 | 118.0 | 14.56 |
| 2024 | Akshaya Tritiya | HYD | A2 Buffalo Milk | 15 | 11769.27 | 11966.0 | 11990.5 | -1.85 | 3.76 | -13.15 | 176539.0 | 2024-03-05 00:00:00 | -7 | 12441.0 | 3.76 |
| 2024 | Akshaya Tritiya | HYD | A2 Desi Cow Milk | 15 | 1161.4 | 1175.0 | 1180.5 | -1.62 | 2.08 | -8.01 | 17421.0 | 2024-10-05 00:00:00 | 0 | 1205.0 | 2.08 |
| 2024 | Akshaya Tritiya | HYD | Cow Milk | 15 | 6631.67 | 6721.0 | 6698.0 | -0.99 | 2.08 | -5.73 | 99475.0 | 2024-04-05 00:00:00 | -6 | 6837.0 | 2.08 |
| 2024 | Akshaya Tritiya | HYD | Curd | 15 | 779.0 | 779.0 | 814.0 | -4.3 | 9.21 | -24.57 | 11685.0 | 2024-06-05 00:00:00 | -4 | 889.0 | 9.21 |
| 2024 | Akshaya Tritiya | HYD | Double Toned A2 Buffalo Milk | 15 | 4327.73 | 4410.0 | 4412.5 | -1.92 | 3.39 | -12.09 | 64916.0 | 2024-03-05 00:00:00 | -7 | 4562.0 | 3.39 |
| 2024 | Akshaya Tritiya | HYD | Skim Milk | 15 | 1832.07 | 1867.0 | 1872.5 | -2.16 | 6.65 | -13.32 | 27481.0 | 2024-03-05 00:00:00 | -7 | 1997.0 | 6.65 |
| 2024 | Diwali | BLR | A2 Buffalo Milk | 15 | 1233.93 | 1254.0 | 1333.5 | -7.47 | 3.71 | -24.26 | 18509.0 | 2024-10-24 00:00:00 | -7 | 1383.0 | 3.71 |
| 2024 | Diwali | BLR | A2 Desi Cow Milk | 15 | 268.0 | 273.0 | 278.0 | -3.6 | 12.95 | -22.66 | 4020.0 | 2024-07-11 00:00:00 | 7 | 314.0 | 12.95 |
| 2024 | Diwali | BLR | Cow Milk | 15 | 1595.93 | 1597.0 | 1719.0 | -7.16 | 2.97 | -22.28 | 23939.0 | 2024-07-11 00:00:00 | 7 | 1770.0 | 2.97 |
| 2024 | Diwali | BLR | Curd | 15 | 157.93 | 148.0 | 141.5 | 11.61 | 55.48 | -35.69 | 2369.0 | 2024-10-30 00:00:00 | -1 | 220.0 | 55.48 |
| 2024 | Diwali | BLR | Double Toned A2 Buffalo Milk | 15 | 301.47 | 299.0 | 319.5 | -5.64 | 7.67 | -22.38 | 4522.0 | 2024-06-11 00:00:00 | 6 | 344.0 | 7.67 |
| 2024 | Diwali | BLR | Skim Milk | 15 | 171.07 | 171.0 | 182.0 | -6.01 | 14.84 | -27.47 | 2566.0 | 2024-10-25 00:00:00 | -6 | 209.0 | 14.84 |
| 2024 | Diwali | HYD | A2 Buffalo Milk | 15 | 14234.6 | 14389.0 | 14484.5 | -1.73 | 5.17 | -8.83 | 213519.0 | 2024-10-31 00:00:00 | 0 | 15234.0 | 5.17 |
| 2024 | Diwali | HYD | A2 Desi Cow Milk | 15 | 1492.53 | 1482.0 | 1510.5 | -1.19 | 10.82 | -9.1 | 22388.0 | 2024-05-11 00:00:00 | 5 | 1674.0 | 10.82 |
| 2024 | Diwali | HYD | Cow Milk | 15 | 8421.93 | 8404.0 | 8470.0 | -0.57 | 10.86 | -6.71 | 126329.0 | 2024-05-11 00:00:00 | 5 | 9390.0 | 10.86 |
| 2024 | Diwali | HYD | Curd | 15 | 1124.47 | 835.0 | 826.5 | 36.05 | 192.08 | -15.43 | 16867.0 | 2024-10-31 00:00:00 | 0 | 2414.0 | 192.08 |
| 2024 | Diwali | HYD | Double Toned A2 Buffalo Milk | 15 | 5431.0 | 5514.0 | 5524.5 | -1.69 | 5.1 | -9.48 | 81465.0 | 2024-10-31 00:00:00 | 0 | 5806.0 | 5.1 |
| 2024 | Diwali | HYD | Skim Milk | 15 | 2066.13 | 2104.0 | 2121.5 | -2.61 | 3.23 | -10.82 | 30992.0 | 2024-10-25 00:00:00 | -6 | 2190.0 | 3.23 |
| 2024 | Diwali Laxmi Puja | BLR | A2 Buffalo Milk | 15 | 1234.6 | 1254.0 | 1333.5 | -7.42 | 4.46 | -24.26 | 18519.0 | 2024-08-11 00:00:00 | 7 | 1393.0 | 4.46 |
| 2024 | Diwali Laxmi Puja | BLR | A2 Desi Cow Milk | 15 | 270.13 | 274.0 | 285.5 | -5.38 | 9.98 | -24.69 | 4052.0 | 2024-07-11 00:00:00 | 6 | 314.0 | 9.98 |
| 2024 | Diwali Laxmi Puja | BLR | Cow Milk | 15 | 1598.0 | 1597.0 | 1719.0 | -7.04 | 2.97 | -22.28 | 23970.0 | 2024-07-11 00:00:00 | 6 | 1770.0 | 2.97 |
| 2024 | Diwali Laxmi Puja | BLR | Curd | 15 | 152.0 | 140.0 | 127.0 | 19.69 | 73.23 | -28.35 | 2280.0 | 2024-10-30 00:00:00 | -2 | 220.0 | 73.23 |
| 2024 | Diwali Laxmi Puja | BLR | Double Toned A2 Buffalo Milk | 15 | 302.8 | 299.0 | 327.0 | -7.4 | 5.2 | -24.16 | 4542.0 | 2024-06-11 00:00:00 | 5 | 344.0 | 5.2 |
| 2024 | Diwali Laxmi Puja | BLR | Skim Milk | 15 | 169.6 | 171.0 | 184.5 | -8.08 | 13.28 | -28.46 | 2544.0 | 2024-10-25 00:00:00 | -7 | 209.0 | 13.28 |
| 2024 | Diwali Laxmi Puja | HYD | A2 Buffalo Milk | 15 | 14235.6 | 14389.0 | 14484.5 | -1.72 | 5.17 | -8.83 | 213534.0 | 2024-10-31 00:00:00 | -1 | 15234.0 | 5.17 |
| 2024 | Diwali Laxmi Puja | HYD | A2 Desi Cow Milk | 15 | 1496.87 | 1482.0 | 1503.0 | -0.41 | 11.38 | -8.65 | 22453.0 | 2024-05-11 00:00:00 | 4 | 1674.0 | 11.38 |
| 2024 | Diwali Laxmi Puja | HYD | Cow Milk | 15 | 8427.47 | 8404.0 | 8500.5 | -0.86 | 10.46 | -7.04 | 126412.0 | 2024-05-11 00:00:00 | 4 | 9390.0 | 10.46 |
| 2024 | Diwali Laxmi Puja | HYD | Curd | 15 | 1122.8 | 835.0 | 794.5 | 41.32 | 203.84 | -12.02 | 16842.0 | 2024-10-31 00:00:00 | -1 | 2414.0 | 203.84 |
| 2024 | Diwali Laxmi Puja | HYD | Double Toned A2 Buffalo Milk | 15 | 5435.4 | 5521.0 | 5539.0 | -1.87 | 4.82 | -9.71 | 81531.0 | 2024-10-31 00:00:00 | -1 | 5806.0 | 4.82 |
| 2024 | Diwali Laxmi Puja | HYD | Skim Milk | 15 | 2061.87 | 2104.0 | 2121.5 | -2.81 | 3.23 | -10.82 | 30928.0 | 2024-10-25 00:00:00 | -7 | 2190.0 | 3.23 |
| 2024 | Dussehra | BLR | A2 Buffalo Milk | 15 | 1129.07 | 1035.0 | 1176.0 | -3.99 | 14.46 | -15.05 | 16936.0 | 2024-10-16 00:00:00 | 4 | 1346.0 | 14.46 |
| 2024 | Dussehra | BLR | A2 Desi Cow Milk | 15 | 263.67 | 261.0 | 272.5 | -3.24 | 8.26 | -10.83 | 3955.0 | 2024-10-16 00:00:00 | 4 | 295.0 | 8.26 |
| 2024 | Dussehra | BLR | Cow Milk | 15 | 1591.07 | 1543.0 | 1672.5 | -4.87 | 6.49 | -13.6 | 23866.0 | 2024-10-17 00:00:00 | 5 | 1781.0 | 6.49 |
| 2024 | Dussehra | BLR | Curd | 15 | 165.93 | 178.0 | 167.5 | -0.94 | 44.48 | -49.85 | 2489.0 | 2024-10-19 00:00:00 | 7 | 242.0 | 44.48 |
| 2024 | Dussehra | BLR | Double Toned A2 Buffalo Milk | 15 | 284.0 | 283.0 | 300.5 | -5.49 | 13.14 | -24.46 | 4260.0 | 2024-10-18 00:00:00 | 6 | 340.0 | 13.14 |
| 2024 | Dussehra | BLR | Skim Milk | 15 | 179.87 | 172.0 | 182.0 | -1.17 | 17.03 | -17.58 | 2698.0 | 2024-10-16 00:00:00 | 4 | 213.0 | 17.03 |
| 2024 | Dussehra | HYD | A2 Buffalo Milk | 15 | 12251.0 | 11460.0 | 12866.0 | -4.78 | 11.57 | -17.22 | 183765.0 | 2024-10-18 00:00:00 | 6 | 14355.0 | 11.57 |
| 2024 | Dussehra | HYD | A2 Desi Cow Milk | 15 | 1327.0 | 1316.0 | 1368.5 | -3.03 | 11.07 | -14.94 | 19905.0 | 2024-10-18 00:00:00 | 6 | 1520.0 | 11.07 |
| 2024 | Dussehra | HYD | Cow Milk | 15 | 7603.73 | 7260.0 | 7780.0 | -2.27 | 9.15 | -9.87 | 114056.0 | 2024-10-18 00:00:00 | 6 | 8492.0 | 9.15 |
| 2024 | Dussehra | HYD | Curd | 15 | 1151.4 | 927.0 | 796.5 | 44.56 | 149.47 | -4.58 | 17271.0 | 2024-05-10 00:00:00 | -7 | 1987.0 | 149.47 |
| 2024 | Dussehra | HYD | Double Toned A2 Buffalo Milk | 15 | 4681.27 | 4437.0 | 4925.5 | -4.96 | 7.85 | -16.94 | 70219.0 | 2024-10-17 00:00:00 | 5 | 5312.0 | 7.85 |
| 2024 | Dussehra | HYD | Skim Milk | 15 | 1939.2 | 1891.0 | 1991.5 | -2.63 | 7.76 | -11.47 | 29088.0 | 2024-10-18 00:00:00 | 6 | 2146.0 | 7.76 |
| 2024 | Ganesh Chaturthi | BLR | A2 Buffalo Milk | 15 | 1167.87 | 1164.0 | 1166.0 | 0.16 | 9.35 | -6.26 | 17518.0 | 2024-07-09 00:00:00 | 0 | 1275.0 | 9.35 |
| 2024 | Ganesh Chaturthi | BLR | A2 Desi Cow Milk | 15 | 302.27 | 304.0 | 307.5 | -1.7 | 4.72 | -15.45 | 4534.0 | 2024-04-09 00:00:00 | -3 | 322.0 | 4.72 |
| 2024 | Ganesh Chaturthi | BLR | Cow Milk | 15 | 1651.6 | 1677.0 | 1678.5 | -1.6 | 3.78 | -9.62 | 24774.0 | 2024-12-09 00:00:00 | 5 | 1742.0 | 3.78 |
| 2024 | Ganesh Chaturthi | BLR | Curd | 15 | 129.33 | 128.0 | 122.5 | 5.58 | 53.47 | -31.43 | 1940.0 | 2024-02-09 00:00:00 | -5 | 188.0 | 53.47 |
| 2024 | Ganesh Chaturthi | BLR | Double Toned A2 Buffalo Milk | 15 | 317.6 | 317.0 | 325.5 | -2.43 | 2.3 | -10.6 | 4764.0 | 2024-11-09 00:00:00 | 4 | 333.0 | 2.3 |
| 2024 | Ganesh Chaturthi | BLR | Skim Milk | 15 | 177.53 | 175.0 | 180.0 | -1.37 | 16.67 | -17.22 | 2663.0 | 2024-04-09 00:00:00 | -3 | 210.0 | 16.67 |
| 2024 | Ganesh Chaturthi | HYD | A2 Buffalo Milk | 15 | 14392.2 | 14288.0 | 14190.0 | 1.43 | 13.62 | -2.64 | 215883.0 | 2024-07-09 00:00:00 | 0 | 16122.0 | 13.62 |
| 2024 | Ganesh Chaturthi | HYD | A2 Desi Cow Milk | 15 | 1484.13 | 1456.0 | 1455.5 | 1.97 | 22.09 | -2.37 | 22262.0 | 2024-07-09 00:00:00 | 0 | 1777.0 | 22.09 |
| 2024 | Ganesh Chaturthi | HYD | Cow Milk | 15 | 8595.6 | 8455.0 | 8425.5 | 2.02 | 21.42 | -1.67 | 128934.0 | 2024-07-09 00:00:00 | 0 | 10230.0 | 21.42 |
| 2024 | Ganesh Chaturthi | HYD | Curd | 15 | 989.87 | 742.0 | 729.0 | 35.78 | 167.9 | -7.27 | 14848.0 | 2024-07-09 00:00:00 | 0 | 1953.0 | 167.9 |
| 2024 | Ganesh Chaturthi | HYD | Double Toned A2 Buffalo Milk | 15 | 5364.33 | 5328.0 | 5308.5 | 1.05 | 12.52 | -3.98 | 80465.0 | 2024-07-09 00:00:00 | 0 | 5973.0 | 12.52 |
| 2024 | Ganesh Chaturthi | HYD | Skim Milk | 15 | 2138.73 | 2125.0 | 2109.5 | 1.39 | 8.51 | -2.35 | 32081.0 | 2024-07-09 00:00:00 | 0 | 2289.0 | 8.51 |
| 2024 | Hanuman Jayanti | BLR | A2 Buffalo Milk | 15 | 680.53 | 683.0 | 683.5 | -0.43 | 7.24 | -10.02 | 10208.0 | 2024-04-17 00:00:00 | -6 | 733.0 | 7.24 |
| 2024 | Hanuman Jayanti | BLR | A2 Desi Cow Milk | 15 | 126.13 | 120.0 | 126.5 | -0.29 | 20.16 | -16.21 | 1892.0 | 2024-04-29 00:00:00 | 6 | 152.0 | 20.16 |
| 2024 | Hanuman Jayanti | BLR | Cow Milk | 15 | 491.73 | 489.0 | 503.5 | -2.34 | 6.06 | -9.43 | 7376.0 | 2024-04-30 00:00:00 | 7 | 534.0 | 6.06 |
| 2024 | Hanuman Jayanti | BLR | Curd | 15 | 61.0 | 56.0 | 60.0 | 1.67 | 81.67 | -23.33 | 915.0 | 2024-04-24 00:00:00 | 1 | 109.0 | 81.67 |
| 2024 | Hanuman Jayanti | BLR | Double Toned A2 Buffalo Milk | 15 | 217.33 | 220.0 | 222.0 | -2.1 | 5.86 | -12.16 | 3260.0 | 2024-04-30 00:00:00 | 7 | 235.0 | 5.86 |
| 2024 | Hanuman Jayanti | BLR | Skim Milk | 15 | 101.4 | 100.0 | 101.0 | 0.4 | 14.85 | -14.85 | 1521.0 | 2024-04-25 00:00:00 | 2 | 116.0 | 14.85 |
| 2024 | Hanuman Jayanti | HYD | A2 Buffalo Milk | 15 | 12546.6 | 12525.0 | 12573.5 | -0.21 | 6.22 | -5.57 | 188199.0 | 2024-04-17 00:00:00 | -6 | 13355.0 | 6.22 |
| 2024 | Hanuman Jayanti | HYD | A2 Desi Cow Milk | 15 | 1247.47 | 1234.0 | 1258.0 | -0.84 | 9.62 | -6.84 | 18712.0 | 2024-04-17 00:00:00 | -6 | 1379.0 | 9.62 |
| 2024 | Hanuman Jayanti | HYD | Cow Milk | 15 | 7101.53 | 7076.0 | 7097.0 | 0.06 | 7.21 | -5.69 | 106523.0 | 2024-04-17 00:00:00 | -6 | 7609.0 | 7.21 |
| 2024 | Hanuman Jayanti | HYD | Curd | 15 | 777.0 | 616.0 | 635.5 | 22.27 | 149.72 | -38.63 | 11655.0 | 2024-04-24 00:00:00 | 1 | 1587.0 | 149.72 |
| 2024 | Hanuman Jayanti | HYD | Double Toned A2 Buffalo Milk | 15 | 4629.73 | 4602.0 | 4646.0 | -0.35 | 8.16 | -3.87 | 69446.0 | 2024-04-17 00:00:00 | -6 | 5025.0 | 8.16 |
| 2024 | Hanuman Jayanti | HYD | Skim Milk | 15 | 1914.27 | 1913.0 | 1899.5 | 0.78 | 6.71 | -4.29 | 28714.0 | 2024-04-17 00:00:00 | -6 | 2027.0 | 6.71 |
| 2024 | Holi | BLR | A2 Buffalo Milk | 15 | 718.27 | 723.0 | 722.5 | -0.59 | 8.1 | -11.28 | 10774.0 | 2024-03-20 00:00:00 | -5 | 781.0 | 8.1 |
| 2024 | Holi | BLR | A2 Desi Cow Milk | 15 | 117.53 | 114.0 | 125.5 | -6.35 | 9.16 | -18.73 | 1763.0 | 2024-03-19 00:00:00 | -6 | 137.0 | 9.16 |
| 2024 | Holi | BLR | Cow Milk | 15 | 473.4 | 475.0 | 478.5 | -1.07 | 5.12 | -9.93 | 7101.0 | 2024-03-22 00:00:00 | -3 | 503.0 | 5.12 |
| 2024 | Holi | BLR | Curd | 15 | 43.6 | 44.0 | 44.5 | -2.02 | 25.84 | -37.08 | 654.0 | 2024-03-20 00:00:00 | -5 | 56.0 | 25.84 |
| 2024 | Holi | BLR | Double Toned A2 Buffalo Milk | 15 | 211.53 | 212.0 | 212.0 | -0.22 | 7.55 | -10.38 | 3173.0 | 2024-03-19 00:00:00 | -6 | 228.0 | 7.55 |
| 2024 | Holi | BLR | Skim Milk | 15 | 103.4 | 103.0 | 107.0 | -3.36 | 18.69 | -17.76 | 1551.0 | 2024-03-18 00:00:00 | -7 | 127.0 | 18.69 |
| 2024 | Holi | HYD | A2 Buffalo Milk | 15 | 12637.8 | 12620.0 | 12791.0 | -1.2 | 2.21 | -4.07 | 189567.0 | 2024-03-20 00:00:00 | -5 | 13074.0 | 2.21 |
| 2024 | Holi | HYD | A2 Desi Cow Milk | 15 | 1294.67 | 1284.0 | 1298.5 | -0.29 | 5.58 | -5.97 | 19420.0 | 2024-03-20 00:00:00 | -5 | 1371.0 | 5.58 |
