# Regional festival calendar policy

The forecasting calendar is city-scoped. A regional event must never activate
festival features for an unrelated city.

| Operating city | Regional scope | 2026 events covered |
| --- | --- | --- |
| HYD | Telangana | Bhogi, Sankranti, Kanuma, Ugadi, Telangana Formation Day, Bonalu, Varalakshmi Vratham, Bathukamma |
| VGA | Andhra Pradesh | Bhogi, Sankranti, Kanuma, Ugadi, Varalakshmi Vratham, Durgashtami, Andhra Pradesh Formation Day |
| BLR | Karnataka | Makara Sankranthi, Ugadi, Basava Jayanti, Onam, Varamahalakshmi Vrata, Maharishi Valmiki Jayanti, Karnataka Rajyotsava |
| PNQ | Maharashtra | Chhatrapati Shivaji Maharaj Jayanti, Gudi Padwa, Maharashtra Day, Ganesh Chaturthi, Diwali Bali Pratipada |

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

## Maintenance rule

Refresh the next year's calendar from official notifications before December.
Moon-sighting holidays must be rechecked when the state announces a date change.
Calendar presence creates scoped model features; any numerical festival adjustment
must still be learned from historical demand windows or approved as a manual rule.
