# Regional festival calendar policy

The forecasting calendar is city-scoped. A regional event must never activate
festival features for an unrelated city.

| Operating city | Regional scope | 2026 events covered |
| --- | --- | --- |
| HYD | Telangana | Bhogi, Sankranti, Kanuma, Ugadi, Telangana Formation Day, the full Bonalu window, Varalakshmi Vratham, Bathukamma |
| VGA | Andhra Pradesh | Bhogi, Sankranti, Kanuma, Ugadi, Varalakshmi Vratham, Durgashtami, Andhra Pradesh Formation Day |
| BLR | Karnataka | Makara Sankranthi, Ugadi, Basava Jayanti, Onam, Varamahalakshmi Vrata, Gowri Habba, Maharishi Valmiki Jayanti, Karnataka Rajyotsava |
| PNQ | Maharashtra | Chhatrapati Shivaji Maharaj Jayanti, Gudi Padwa, Maharashtra Day, Ashadhi Ekadashi, Dahi Handi, Ganesh Chaturthi, Gauri Puja, Anant Chaturdashi, Diwali Bali Pratipada |

National festivals remain scoped to `ALL`. Regional rows use comma-separated city
codes such as `HYD,VGA`. Unknown demand direction is recorded as `0`; the system
does not invent an uplift or downshift without historical Redash evidence.

## Authoritative sources

- Telangana State Portal, Calendar 2026: https://www.telangana.gov.in/downloads/calendar-2026/
- Hyderabad District Government, Bonalu: https://hyderabad.telangana.gov.in/festival/bonalu/
- Telangana Tourism, festivals and fairs: https://www.tourism.telangana.gov.in/page/festivals-and-fairs
- Andhra Pradesh G.O. Rt. No. 2276 dated 4 December 2025: https://www.aputf.org/wp-content/uploads/2025/12/2025GAD_RT2276_E.pdf
- CAG holiday list for Central Government offices in Karnataka, 2026: https://cag.gov.in/uploads/media/Holiday-List-2026-069521fe6f358d0-89936988.pdf
- Government of Maharashtra, Public Holidays 2026: https://maharashtra.gov.in/site/Upload/pdf/Public-Holiday-2026.pdf
- Government of Maharashtra, Public Holidays 2025: https://www.maharashtra.gov.in/site/Upload/pdf/Maharashtra_Holiday_2025.pdf
- Government of Maharashtra, Public Holidays 2024: https://maharashtra.gov.in/site/Upload/pdf/Public_Holidays_2024.pdf
- Karnataka Tourism, Gowri Habba: https://karnatakatourism.org/en/experiences/gowri-habba
- Maharashtra Tourism, Ganesh Chaturthi: https://maharashtratourism.gov.in/festivals/ganesh-chaturthi/
- Maharashtra Tourism, Gauri Aagman: https://maharashtratourism.gov.in/festivals/gauri-aagman/

## 2026 re-audit completed on 20 August 2026

The calendar was checked city by city instead of applying one national date to
every market. The audit corrected these material problems:

- Ram Navami is 26 March for BLR/PNQ and 27 March for HYD/VGA.
- Holi/Holika Dahan is state-scoped because Karnataka observes the sequence one
  day later than Telangana, Andhra Pradesh, and Maharashtra.
- Moharram on 26 June now applies to all four operating cities, including VGA.
- Naga Panchami was incorrectly copied from the 2025 date of 29 July; its 2026
  date is 17 August and it now covers PNQ too.
- Bonalu is represented as a Hyderabad event window (16/19/26 July and 2/9/10
  August), not only as the 10 August public holiday.
- Missing Karnataka and Maharashtra demand events were added without inventing
  uplift percentages. Their initial `impact_direction` is zero until historical
  Redash evidence supports a product-level adjustment.

Run the following before every monthly planning review and whenever a state
announces a changed lunar-holiday date:

```powershell
python scripts\audit_festival_calendar.py --as-of 2026-08-20 --lookahead-days 45
```

## Maintenance rule

Refresh the next year's calendar from official notifications before December.
Moon-sighting holidays must be rechecked when the state announces a date change.
Calendar presence creates scoped model features; any numerical festival adjustment
must still be learned from historical demand windows or approved as a manual rule.

Operationally, review every `HIGH` event 30 days ahead, extract the same event's
city/SKU demand windows for at least the previous two years, approve any guardrail
seven days before the first procurement issue date, and compare actuals on D+1.
The calendar audit prevents missing/wrong dates; it cannot prevent Redash network
outages, which remain a separate infrastructure dependency.
