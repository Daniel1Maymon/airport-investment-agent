# Data sources: how to download each one

Every method here was tested by real download on 2026-10-30. Why each source was chosen, and what the data showed, is in [decisions.md](decisions.md) (sections 2, 3). What gets stored is in [schema.md](schema.md).

Downloaded files are untrusted: keep them in their own directory and run any Python that reads them with `python3 -I`.

## Where the raw files go

`python -m loader.build --raw data/raw --out airports.duckdb` (Step 5) expects these files, the same names the download functions write. It downloads only the ones that are missing.

| Folder | Files |
|---|---|
| `data/raw/ourairports/` | `airports.csv`, `runways.csv` |
| `data/raw/faa/` | `arp-cy2024-commercial-service-enplanements.xlsx`, `arp-cy2025-…` |
| `data/raw/t100/` | `t100_2019.zip`, `t100_2024.zip`, `t100_2025.zip` |
| `data/raw/ontime/` | `ontime_2025_1.zip` … `ontime_2025_12.zip` (month without a leading zero) |

The years and months are constants at the top of `loader/build.py` (`FAA_YEARS`, `T100_YEARS`, `ONTIME_YEAR`, `ONTIME_MONTHS`). After loading, the build checks that each of the four tables has at least one row; an empty table stops it, and no database file is written.

## A. OurAirports: airports and runways

- `https://davidmegginson.github.io/ourairports-data/airports.csv`
- `https://davidmegginson.github.io/ourairports-data/runways.csv`
- Plain GET, no key.
- `airports.csv` columns: `id, ident, type, name, latitude_deg, longitude_deg, elevation_ft, continent, iso_country, iso_region, municipality, scheduled_service, icao_code, iata_code, gps_code, local_code, home_link, wikipedia_link, keywords`.
- Filter: `iso_country = 'US'`, `scheduled_service = 'yes'`, non-empty `iata_code` → **679 airports**. US territories have their own country codes, so they drop out (decided: excluded).
- State = `iso_region` without the `US-` prefix.
- `local_code` holds the **FAA code**. It is the translation table from FAA codes to IATA codes (decisions 7.6).

## B. FAA enplanements (passenger boardings)

- `https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2025-commercial-service-enplanements.xlsx`
- Same URL with `cy2024`. Each file also has the previous year, so the two files cover **2023–2025**.
- One sheet. Columns: `Rank, RO, ST, Locid, City, Airport Name, S/L, Hub, CY 25 Enplanements, CY 24 Enplanements, % Change` (year labels change per file; checked on the real files 2026-10-31).
- Summary rows at the bottom have no `Rank`, a count in `Locid` and a label in `City` (e.g. `Large Count`); some rows are blank. `Hub` is `L`/`M`/`S`/`N`, or the text `None` for airports the FAA gives no hub group (stored as empty).
- `Locid` is the **FAA code**, not always the IATA code: 33 of 522 rows in 2025 differ (e.g. `IWA` = `AZA`). Convert via OurAirports `local_code`. Some rows are summary rows with no airport.
- The file is small (~58 KB). It was parsed with Python's built-in `zipfile` + XML because no Excel library was installed; in the app, use a proper library.

## C. BTS T-100 Segment, All Carriers (routes: flights, seats, passengers, distance)

- Table page: `https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45`
- **No direct download link.** The page is an ASP.NET form, so the loader must:
  1. GET the page with a cookie jar and read the hidden fields `__VIEWSTATE`, `__EVENTVALIDATION`, etc.
  2. POST back to the same URL with those hidden fields plus `cboGeography=All`, `cboYear=<year>`, `cboPeriod=All`, `chkDownloadZip=on`, `btnDownload=Download`, and `<FIELD>=on` for each column wanted.
- Columns requested: `DEPARTURES_SCHEDULED, DEPARTURES_PERFORMED, SEATS, PASSENGERS, FREIGHT, DISTANCE, UNIQUE_CARRIER, CARRIER_NAME, ORIGIN, ORIGIN_STATE_ABR, ORIGIN_COUNTRY, DEST, DEST_STATE_ABR, DEST_COUNTRY, DEST_COUNTRY_NAME, AIRCRAFT_TYPE, YEAR, MONTH, CLASS`.
- Result: a zip with two files, `Documentation.csv` (field list) and `T_T100_SEGMENT_ALL_CARRIER.csv`, ~7–8 MB zipped / ~61 MB CSV, ~50 s per year. Rows (checked 2026-10-31): 2019 487,923; 2024 549,799; 2025 571,205. Counts are written with two decimals (`4.00`); carrier names with a comma are in quotes.
- Palm Beach is `PBI` in every year; the loader renames it to `DJT` (decisions 7.6).
- Years 1990–2026 available. We load 2019, 2024, 2025.
- Risk: if BTS changes the page, the script breaks. The loader should fail loudly.
- Do **not** use the "Domestic Segment, US carriers only" table: it misses international and foreign-carrier flights (e.g. most Anchorage cargo).

Tested probe (Python standard library only):

```python
import re, sys, urllib.request, urllib.parse, http.cookiejar
url = "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45"
year, out = sys.argv[1], sys.argv[2]
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
op.addheaders = [("User-Agent", "Mozilla/5.0")]
h = op.open(url, timeout=60).read().decode("utf-8", "replace")
hidden = {n: v for n, v in re.findall(r'<input[^>]*name="(__[A-Z]+)"[^>]*value="([^"]*)"', h)}
fields = ["DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "FREIGHT", "DISTANCE",
          "UNIQUE_CARRIER", "CARRIER_NAME", "ORIGIN", "ORIGIN_STATE_ABR", "DEST", "DEST_STATE_ABR",
          "AIRCRAFT_TYPE", "YEAR", "MONTH", "CLASS", "ORIGIN_COUNTRY", "DEST_COUNTRY", "DEST_COUNTRY_NAME"]
data = dict(hidden, cboGeography="All", cboYear=year, cboPeriod="All", chkDownloadZip="on", btnDownload="Download")
data.update({f: "on" for f in fields})
r = op.open(urllib.request.Request(url, data=urllib.parse.urlencode(data).encode()), timeout=600)
open(out, "wb").write(r.read())
```

## D. BTS On-Time Performance (delays, causes, taxi times)

- `https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip` (month without leading zero, e.g. `2025_6`).
- One flight per row, domestic flights of the larger US airlines only. ~24–31 MB zip / ~240 MB CSV per month (January 2025: 539,747 flights). A download took ~3.5 min per month when first tested and about 1 min per month on 2026-10-31, so the speed depends on the BTS server. Latest month seen: 2026_6. We load the 12 months of **2025** (~340 MB of zips, ~3 GB of CSV, one time).
- The zip holds the data file, named after the year and month (`On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_1.csv`), plus `readme.html`; the loader finds the CSV by its `.csv` ending. 110 columns; every line ends with a comma (an empty last column).
- Palm Beach is still `PBI` here (5,886 times in January 2025); the loader renames it to `DJT` (decisions 7.6).
- **Coverage (checked 2026-10-31, Step 4):** 2025 gives 7,898 rows for **341 of our 679 airports**, 6,953,969 departures. The other 338 airports are small ones served only by smaller or commuter airlines that don't report to On-Time. Of the 227 airports with 100,000+ boardings in 2025, only **2 have no delay data**: Tweed New Haven (`HVN`, CT, 737,789 boardings) and Wilmington (`ILG`, DE, 169,382), both served mainly by Avelo. Airports with delay data hold 99.7% of 2025 boardings. Airports without it are scored by the missing-delay rule ([scoring.md](scoring.md)).
- Must be **reduced to totals per airport × month × direction while loading** (see `airport_delays` in [schema.md](schema.md)).
- DuckDB reads `.gz` but not `.zip`: unpack with Python's `zipfile` first.
- Delay-cause minutes (carrier, weather, NAS, security, late aircraft) are filled only for flights that arrived 15+ minutes late.

## E. FAA live airport status (optional context, never scored)

- `https://nasstatus.faa.gov/api/airport-status-information` (XML): current closures and delays.

## Known gap

No public source for terminal size or gate counts. Runways and traffic are used as stand-ins.
