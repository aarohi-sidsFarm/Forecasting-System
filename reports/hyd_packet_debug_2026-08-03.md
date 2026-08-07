# HYD packet-error audit ? 2026-08-03

- Finalized scoring window: 2026-07-23 through 2026-08-02
- Acceptance rule: absolute error < 100 packets
- Completed rows: 77
- Completed breaches: 24
- Completed compliance: 68.83%
- 2026-08-03 is provisional and excluded from finalized compliance.

## Product summary

```csv
product_name,rows,mae_packets,max_error_packets,breaches,compliance_pct
Toned Milk,11,171.27,644,8,27.27
A2 Buffalo Milk,11,149.18,504,6,45.45
Cow Milk,11,129.55,382,4,63.64
Skim Milk,11,54.55,173,2,81.82
Curd,11,54.0,131,2,81.82
Double Toned A2 Buffalo Milk,11,54.18,131,1,90.91
A2 Desi Cow Milk,11,44.36,104,1,90.91
```

## 1?2 August breaches

```csv
forecast_date,product_name,forecast_quantity,actual_quantity,difference,absolute_error_packets
2026-08-01,A2 Buffalo Milk,16590,16794,-204,204
2026-08-02,A2 Buffalo Milk,16114,16342,-228,228
2026-08-02,Cow Milk,9079,9357,-278,278
2026-08-02,Toned Milk,9594,9705,-111,111
```

## Data warning

This audit reflects the supplied comparison. Replace it with the canonical Redash selected-final-actual export when connectivity is restored.