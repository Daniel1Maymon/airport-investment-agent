# The tiny dataset

Built by `build_tiny_db(path)` in `tests/fixtures/tiny_data.py`. All values are made up, with round numbers so tests can work them out by hand. Locations and names are roughly real.

**Frozen after Step 0:** later steps may **add** rows or airports (and record them here), never change these values.

## Why each airport is there

| Airport | Why |
|---|---|
| BOS (MA, large) | New England, big, 4 runways, two airlines (B6, DL). The only airport with one 2025 month over 85% full (July, 88.4%) and one under 80% (January, 70%): the unmet-demand range case. |
| MHT (NH) | New England, fastest growth on both growth measures (D1 50%, D2 20%). |
| BTV (VT) | New England, **no delay rows at all** (missing-data rule: S2 and S3 skipped). |
| BHB (ME) | **Under 100,000 boardings** every year (size filter). Its growth is lower than MHT's on purpose. |
| LAX (CA, Los Angeles) | Big and busy, highest NAS delay and taxi-out, one **international** route (to MEX, Mexico) that is **not** long-haul. |
| SNA (CA, Santa Ana) | About 35 miles from LAX, **1 runway**, for the name resolver and the LAX/SNA comparison. |
| ANC (AK) | **Cargo** (more cargo departures than passenger ones) and one **3,000+ mile** passenger route (to ATL) that is **domestic**: long-haul is not the same as international. |

## Conventions

- Every airport has rows in **January (1) and July (7)** of **2019, 2024 and 2025**, the same months every year, so whole-year totals compare fairly.
- `dest_country` is a 2-letter code; the US is `'US'`.
- `is_passenger` = `passengers > 0`. Cargo rows have `seats = 0`, `passengers = 0`, `freight_lbs > 0`.
- Departures, seats, freight and distance of a route are the same in every month and year; only passengers change.
- Delay rows: 2025 only, months 1 and 7, the same values in both months. Cause minutes are on `arr` rows only (NULL on `dep` rows).
- `aircraft_type` numbers are BTS-style codes, not checked against the real list.
- Among the 6 airports with 100,000+ boardings (all but BHB), D1, D2, S1, S2, S3 and S4 have **no ties**. No load factor is exactly 80% or 85%, and no distance is exactly 3,000.

## Table `airports`

| iata | name | city | state | lat | lon | size_class | runway_count | longest_runway_ft |
|---|---|---|---|---|---|---|---|---|
| BOS | General Edward Lawrence Logan International Airport | Boston | MA | 42.36 | -71.01 | large | 4 | 10083 |
| MHT | Manchester-Boston Regional Airport | Manchester | NH | 42.93 | -71.44 | medium | 2 | 9250 |
| BTV | Burlington International Airport | South Burlington | VT | 44.47 | -73.15 | medium | 2 | 8320 |
| BHB | Hancock County-Bar Harbor Airport | Bar Harbor | ME | 44.45 | -68.36 | small | 2 | 5200 |
| LAX | Los Angeles International Airport | Los Angeles | CA | 33.94 | -118.41 | large | 4 | 12923 |
| SNA | John Wayne Airport-Orange County Airport | Santa Ana | CA | 33.68 | -117.87 | medium | 1 | 5701 |
| ANC | Ted Stevens Anchorage International Airport | Anchorage | AK | 61.17 | -149.98 | large | 3 | 12400 |

(BOS really has 6 runways; 4 here keeps the runway-load numbers round.)

## Table `enplanements`

| iata | hub_type | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| BOS | L | 19,000,000 | 20,000,000 | 21,000,000 |
| MHT | S | 900,000 | 1,000,000 | 1,200,000 |
| BTV | S | 580,000 | 600,000 | 618,000 |
| BHB | N | 40,000 | 50,000 | 55,000 |
| LAX | L | 35,000,000 | 36,000,000 | 38,160,000 |
| SNA | M | 4,900,000 | 5,000,000 | 5,100,000 |
| ANC | M | 2,400,000 | 2,500,000 | 2,600,000 |

21 rows (7 airports x 3 years).

## Table `route_traffic`

One row per route per (year, month): 11 routes x 3 years x 2 months = **66 rows**. `freight_lbs` is 0 on every passenger row.

| origin | dest | dest_country | carrier | carrier_name | aircraft_type | departures | seats | freight_lbs | distance_mi |
|---|---|---|---|---|---|---|---|---|---|
| BOS | MCO | US | B6 | JetBlue Airways | 694 | 10 | 1000 | 0 | 1121 |
| BOS | ATL | US | DL | Delta Air Lines Inc. | 694 | 10 | 1000 | 0 | 946 |
| MHT | BWI | US | WN | Southwest Airlines Co. | 612 | 8 | 1000 | 0 | 377 |
| BTV | ORD | US | AA | American Airlines Inc. | 673 | 5 | 500 | 0 | 763 |
| BHB | BOS | US | 9K | Hyannis Air Service Inc. (Cape Air) | 35 | 10 | 90 | 0 | 151 |
| LAX | JFK | US | AA | American Airlines Inc. | 614 | 20 | 2000 | 0 | 2475 |
| LAX | MEX | MX | AM | Aerovias de Mexico | 694 | 10 | 1000 | 0 | 1555 |
| SNA | SJC | US | WN | Southwest Airlines Co. | 612 | 6 | 600 | 0 | 342 |
| ANC | SEA | US | AS | Alaska Airlines Inc. | 614 | 10 | 1000 | 0 | 1448 |
| ANC | ATL | US | DL | Delta Air Lines Inc. | 622 | 10 | 1000 | 0 | 3417 |
| ANC | SDF | US | 5X | United Parcel Service | 627 | 25 | 0 | 3,000,000 | 2864 |

Passengers per row (the `ANC-SDF` cargo row is always 0, `is_passenger` false; every other row is true):

| Route | 2019 Jan | 2019 Jul | 2024 Jan | 2024 Jul | 2025 Jan | 2025 Jul |
|---|---|---|---|---|---|---|
| BOS-MCO (B6) | 720 | 720 | 700 | 800 | 700 | 884 |
| BOS-ATL (DL) | 720 | 720 | 700 | 800 | 700 | 884 |
| MHT-BWI | 600 | 600 | 750 | 750 | 840 | 960 |
| BTV-ORD | 350 | 350 | 350 | 350 | 350 | 378 |
| BHB-BOS | 45 | 45 | 50 | 50 | 54 | 54 |
| LAX-JFK | 1600 | 1600 | 1600 | 1600 | 1640 | 1640 |
| LAX-MEX | 800 | 800 | 800 | 800 | 820 | 820 |
| SNA-SJC | 480 | 480 | 480 | 480 | 504 | 504 |
| ANC-SEA | 800 | 800 | 800 | 800 | 864 | 864 |
| ANC-ATL | 800 | 800 | 800 | 800 | 864 | 864 |
| ANC-SDF (cargo) | 0 | 0 | 0 | 0 | 0 | 0 |

## Table `airport_delays`

2025, months 1 and 7, a `dep` and an `arr` row each: 6 airports x 2 months x 2 directions = **24 rows**. BTV has none. The values are the same in January and July.

| iata | flights (dep and arr) | dep cancelled | dep delayed_15 | taxi-out (dep avg_taxi_min) | arr cancelled | arr delayed_15 | taxi-in (arr avg_taxi_min) | nas | carrier | weather | late_aircraft | security |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BOS | 100 | 2 | 20 | 20 | 2 | 22 | 8 | 800 | 600 | 300 | 700 | 0 |
| MHT | 100 | 1 | 10 | 12 | 1 | 10 | 5 | 100 | 400 | 100 | 300 | 0 |
| BHB | 10 | 0 | 1 | 10 | 0 | 1 | 4 | 0 | 10 | 20 | 0 | 0 |
| LAX | 100 | 3 | 25 | 22 | 3 | 26 | 10 | 1000 | 700 | 100 | 800 | 10 |
| SNA | 100 | 1 | 15 | 14 | 1 | 16 | 6 | 300 | 500 | 50 | 400 | 0 |
| ANC | 100 | 2 | 12 | 16 | 2 | 14 | 7 | 200 | 300 | 600 | 300 | 0 |

Cause columns (`nas_delay_min` ... `security_delay_min`) are minutes per month on the `arr` row; NULL on the `dep` row.

## Table `data_sources`

`loaded_at` is `2026-10-31 12:00:00` on every row. `row_count` is the row count of the table the source fills.

| source | url | period | row_count |
|---|---|---|---|
| OurAirports | https://davidmegginson.github.io/ourairports-data/airports.csv | current | 7 |
| FAA enplanements | https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2025-commercial-service-enplanements.xlsx | 2023, 2024, 2025 | 21 |
| BTS T-100 Segment | https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45 | 2019, 2024, 2025 | 66 |
| BTS On-Time | https://www.transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip | 2025 | 24 |

## Hand-worked numbers (checked against the built database)

Departing passenger rows only (`origin = airport`, `is_passenger`), unless stated.

**Passengers per year and growth D1 (2019 -> 2025):**

| Airport | 2019 | 2024 | 2025 | D1 |
|---|---|---|---|---|
| BOS | 2,880 | 3,000 | 3,168 | 288 / 2,880 = 10% |
| MHT | 1,200 | 1,500 | 1,800 | 600 / 1,200 = 50% |
| BTV | 700 | 700 | 728 | 28 / 700 = 4% |
| BHB | 90 | 100 | 108 | 18 / 90 = 20% |
| LAX | 4,800 | 4,800 | 4,920 | 120 / 4,800 = 2.5% |
| SNA | 960 | 960 | 1,008 | 48 / 960 = 5% |
| ANC | 3,200 | 3,200 | 3,456 | 256 / 3,200 = 8% |

**Growth D2 (enplanements 2024 -> 2025):** BOS 5%, MHT 20%, BTV 3%, BHB 10%, LAX 6% (2,160,000 / 36,000,000), SNA 2%, ANC 4%.

**Load factor 2025 (passengers / seats):**

| Airport | January | July | Year (S1) |
|---|---|---|---|
| BOS | 1,400 / 2,000 = 70% | 1,768 / 2,000 = 88.4% | 3,168 / 4,000 = 79.2% |
| MHT | 840 / 1,000 = 84% | 960 / 1,000 = 96% | 1,800 / 2,000 = 90% |
| BTV | 350 / 500 = 70% | 378 / 500 = 75.6% | 728 / 1,000 = 72.8% |
| BHB | 54 / 90 = 60% | 60% | 108 / 180 = 60% |
| LAX | 2,460 / 3,000 = 82% | 82% | 4,920 / 6,000 = 82% |
| SNA | 504 / 600 = 84% | 84% | 1,008 / 1,200 = 84% |
| ANC | 1,728 / 2,000 = 86.4% | 86.4% | 3,456 / 4,000 = 86.4% |

**Unmet demand 2025** (per month: missing = passengers / target - seats, 0 if negative; then add the months):

| Airport | At 80% (high estimate) | At 85% (low estimate) | Seats offered |
|---|---|---|---|
| BOS | Jan 0; Jul 1,768/0.8 = 2,210 - 2,000 = 210. **210** | Jan 0; Jul 1,768/0.85 = 2,080 - 2,000 = 80. **80** | 4,000 |
| MHT | Jan 840/0.8 = 1,050 - 1,000 = 50; Jul 960/0.8 = 1,200 - 1,000 = 200. **250** | Jan 0 (988.2 < 1,000); Jul 1,129.41 - 1,000 = 129.41. **129.41** | 2,000 |
| LAX | 2,460/0.8 = 3,075 - 3,000 = 75 per month. **150** | 0 (2,894.1 < 3,000) | 6,000 |
| SNA | 504/0.8 = 630 - 600 = 30 per month. **60** | 0 (592.9 < 600) | 1,200 |
| ANC | 1,728/0.8 = 2,160 - 2,000 = 160 per month. **320** | 2,032.94 - 2,000 = 32.94 per month. **65.88** | 4,000 |
| BTV, BHB | 0 | 0 | 1,000 / 180 |

BOS is the clean case: 100 seats per departure on every row, so missing flights = 210 / 100 = **2.1** at 80% and 80 / 100 = **0.8** at 85%; `missing_seats_pct` = 210 / 4,000 = 5.25% and 80 / 4,000 = 2%.

**Runway load S4 (all 2025 departures, passenger and cargo, / runways):** BOS 40 / 4 = 10; MHT 16 / 2 = 8; BTV 10 / 2 = 5; BHB 20 / 2 = 10; LAX 60 / 4 = 15; SNA 12 / 1 = 12; ANC 90 / 3 = 30.

**Delays 2025** (both months added; values are the same in both months):

| Airport | S2 NAS per arriving flight | S3 taxi-out | late_share (dep) | cancel_rate (dep) |
|---|---|---|---|---|
| BOS | 1,600 / 200 = 8 | 20 | 40 / 200 = 20% | 4 / 200 = 2% |
| MHT | 200 / 200 = 1 | 12 | 10% | 1% |
| BHB | 0 / 20 = 0 | 10 | 10% | 0% |
| LAX | 2,000 / 200 = 10 | 22 | 25% | 3% |
| SNA | 600 / 200 = 3 | 14 | 15% | 1% |
| ANC | 400 / 200 = 2 | 16 | 12% | 2% |
| BTV | no data | no data | no data | no data |

**Flight mix 2025:**
- ANC long-haul share: ATL route 20 of 40 passenger departures = **50%**; international share **0%**; cargo share 50 of 90 departures = **55.6%**.
- LAX international share: MEX route 10 of 30 passenger departures = **33.3%**; long-haul share **0%**.
- Every other airport: long-haul 0%, international 0%, cargo 0%.
- Top airline share: BOS 50% (B6 and DL tie, 20 of 40); LAX AA 40 of 60 = 66.7%; ANC 50% (AS and DL tie, 20 of 40 passenger departures); MHT, BTV, BHB, SNA 100%.

## Step 3 sample: t100_sample.zip

`tests/fixtures/raw/t100_sample.zip` is a made-up BTS T-100 download, built by `tests/fixtures/make_t100_sample.py` (`.venv/bin/python -m tests.fixtures.make_t100_sample`). It copies the real file's format: the zip holds `Documentation.csv` (field list) and `T_T100_SEGMENT_ALL_CARRIER.csv`; CRLF line endings; the 6 number columns written as `10.00`; quotes around a carrier name with a comma; empty state for foreign airports. It is separate from the tiny database above. All rows are year 2025.

| Row | Sched | Performed | Seats | Pass. | Freight | Dist. | Carrier | Route | Dest country | Month | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | 10 | 10 | 1,000 | 800 | 0 | 187 | B6 | BOS→JFK | US | 1 | |
| R2 | 10 | 10 | 1,000 | 900 | 0 | 187 | B6 | JFK→BOS | US | 1 | |
| R3 | 20 | 20 | 3,000 | 2,500 | 0 | 2,611 | AA | LAX→BOS | US | 1 | |
| R4 | 20 | 20 | 3,000 | 2,400 | 0 | 2,611 | AA | BOS→LAX | US | 1 | |
| R5 | **12** | **10** | 1,500 | 1,200 | 500 | 372 | AS | SNA→SFO | US | 2 | scheduled ≠ performed; passengers and freight |
| R6 | 10 | 10 | 1,500 | 1,300 | 0 | 372 | AS | SFO→SNA | US | 2 | |
| R7 | 5 | 5 | 0 | 0 | 100,000 | 5,063 | 5X | ANC→HKG | **HK** | 3 | cargo, foreign destination, empty dest state |
| R8 | 5 | 5 | 0 | 0 | 80,000 | 5,063 | 5X | HKG→ANC | US | 3 | cargo, foreign origin |
| R9 | 4 | 4 | 0 | 0 | 40,000 | 1,448 | FX | ANC→SEA | US | 3 | cargo |
| R10 | 2 | 2 | 40 | 30 | 0 | 17 | F4 | CPX→VQS | US | 8 | carrier name `"Air Charter, Inc d/b/a Air Flamenco"` |
| R11 | 8 | 8 | 800 | 600 | 0 | 184 | DL | BOS→LGA | US | 4 | identical to R12 |
| R12 | 8 | 8 | 800 | 600 | 0 | 184 | DL | BOS→LGA | US | 4 | identical to R11 |
| R13 | 0 | 0 | 0 | 0 | 0 | 0 | 4W | FAI→FAI | US | 3 | all zero, like the real Warbelow line |
| R14 | 6 | 6 | 900 | 700 | 0 | 1,846 | UA | SFO→ORD | US | 5 | |
| R15 | 6 | 6 | 900 | 800 | 0 | 1,846 | UA | ORD→SFO | US | 5 | |
| R16 | 4 | 4 | 1,000 | 900 | 2,000 | 5,451 | JL | LAX→NRT | **JP** | 6 | passenger flight abroad |
| R17 | 12 | 12 | 1,800 | 1,500 | 0 | 236 | WN | SNA→SJC | US | 7 | |
| R18 | 12 | 12 | 1,800 | 1,600 | 0 | 236 | WN | SJC→SNA | US | 7 | |
| R19 | 3 | 3 | 300 | 0 | 0 | 1,448 | AS | SEA→ANC | US | 9 | seats but no passengers |
| R20 | 5 | 5 | 500 | 400 | 0 | 187 | B6 | BOS→JFK | US | 12 | |

**Hand-worked totals (20 rows):**
- Passengers: 800 + 900 + 2,500 + 2,400 + 1,200 + 1,300 + 0 + 0 + 0 + 30 + 600 + 600 + 0 + 700 + 800 + 900 + 1,500 + 1,600 + 0 + 400 = **16,230**.
- Departures performed: 10+10+20+20+10+10+5+5+4+2+8+8+0+6+6+4+12+12+3+5 = **160** (scheduled would give 162).
- Seats: 1,000+1,000+3,000+3,000+1,500+1,500+0+0+0+40+800+800+0+900+900+1,000+1,800+1,800+300+500 = **19,840**.
- Freight: 500 + 100,000 + 80,000 + 40,000 + 2,000 = **222,500** lbs.
- `is_passenger` true: R1–R6, R10–R12, R14–R18, R20 = **15**; false: R7, R8, R9, R13, R19 = **5**.
- `dest_country`: US 18, HK 1 (R7), JP 1 (R16).
- Duplicate pair R11 + R12: 2 rows, 600 + 600 = 1,200 passengers.

The two-zip test adds a 2024 zip built in `tmp_path` (3 rows: B6 BOS→JFK 100 passengers, AA LAX→BOS 200, 5X ANC→HKG cargo 0): 3 rows, **300** passengers.

## Step 4 sample: ontime_sample.zip

`tests/fixtures/raw/ontime_sample.zip` is a made-up BTS On-Time download, built by `tests/fixtures/make_ontime_sample.py` (`.venv/bin/python -m tests.fixtures.make_ontime_sample`). It copies the real January 2025 file's format: the zip holds `On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_1.csv` and `readme.html`; all 110 columns in the real order, with the header names in double quotes and a trailing comma on every line (so the 110th column has an empty name); LF line endings; text in double quotes (`""` when empty); whole numbers such as `Year`, `Month` and airport IDs without decimals; measured numbers with two decimals (`23.00`); empty numbers written as nothing. Cancelled flights have no DepDel15, ArrDel15, TaxiOut or TaxiIn; the diverted flight has a TaxiIn but no ArrDel15; cause minutes are filled only on flights that arrived 15+ minutes late, and add up to the arrival delay. Palm Beach is written `PBI`, as in the real January file. It is separate from the tiny database above.

The one CSV holds both months (January and February 2025); year and month come from the `Year` and `Month` columns. The tests insert their own airports: **JFK, LAX, BOS, DJT, SFO** (SFO has no flights). **PSE** (Ponce, Puerto Rico) is not in the list; **PBI** becomes DJT through `CODE_RENAMES`.

| Flight | Month | Airline | Route | Kind | Dep delay | Arr delay | Taxi-out | Taxi-in | Causes (minutes) |
|---|---|---|---|---|---|---|---|---|---|
| F1 | 1 | AA | JFK→LAX | | -3 | -7 | 20 | 10 | |
| F2 | 1 | AA | JFK→LAX | | 0 | -5 | 30 | 6 | |
| F3 | 1 | AA | JFK→LAX | late both ends | 110 | 120 | 40 | 8 | carrier 100, NAS 20 |
| F4 | 1 | AA | JFK→LAX | **cancelled** (A) | | | | | |
| F5 | 1 | B6 | JFK→BOS | | -2 | -4 | 10 | 4 | |
| F6 | 1 | B6 | BOS→JFK | late on arrival only | 5 | 30 | 25 | 12 | NAS 30 |
| F7 | 1 | B6 | BOS→JFK | **cancelled** (B) | | | | | |
| F8 | 1 | AA | LAX→JFK | | -1 | -10 | 18 | 9 | |
| F9 | 1 | AA | LAX→JFK | **diverted** (via LAS) | 2 | (none) | 14 | 15 | |
| F10 | 1 | DL | LAX→BOS | late both ends | 70 | 80 | 22 | 7 | weather 50, NAS 10, security 5, late aircraft 15 |
| F11 | 1 | B6 | **PSE**→JFK | from an unlisted airport | 0 | -2 | 12 | 11 | |
| F12 | 1 | B6 | JFK→**PSE** | to an unlisted airport, late | 50 | 60 | 35 | 5 | carrier 60 (dropped with the PSE side) |
| F13 | 1 | B6 | **PBI**→JFK | Palm Beach, old code | -4 | -6 | 16 | 13 | |
| F14 | 1 | B6 | JFK→**PBI** | late on arrival only | 10 | 40 | 24 | 6 | late aircraft 40 |
| F15 | 1 | B6 | BOS→LAX | | 0 | 3 | 20 | 10 | |
| F16 | 2 | AA | JFK→LAX | | 1 | -3 | 25 | 5 | |
| F17 | 2 | AA | JFK→LAX | **cancelled** (C) | | | | | |
| F18 | 2 | AA | JFK→LAX | late both ends | 85 | 90 | 45 | 15 | NAS 60, late aircraft 30 |
| F19 | 2 | AA | LAX→JFK | | -5 | -8 | 15 | 7 | |
| F20 | 2 | AA | LAX→JFK | | 3 | 0 | 17 | 9 | |
| F21 | 2 | B6 | BOS→JFK | | -2 | -1 | 19 | 11 | |
| F22 | 2 | B6 | JFK→BOS | late on departure only | 20 | 10 | 20 | 3 | |
| F23 | 2 | B6 | JFK→BOS | **cancelled** (A) | | | | | |
| F24 | 2 | B6 | **PSE**→JFK | from an unlisted airport, late | 8 | 25 | 10 | 20 | weather 25 |
| F25 | 2 | B6 | **PBI**→BOS | Palm Beach, old code | 0 | 2 | 14 | 8 | |
| F26 | 2 | B6 | BOS→**PBI** | **cancelled** (B) | | | | | |
| F27 | 2 | DL | BOS→LAX | late both ends | 40 | 45 | 30 | 10 | carrier 45 |
| F28 | 2 | AA | LAX→JFK | **cancelled** (A) | | | | | |

"Late" means 15+ minutes (DepDel15 / ArrDel15 = 1).

**Hand-worked `airport_delays` rows (16 = 4 airports × 2 months × 2 directions, all 2025):**

| iata | month | dir | flights | cancelled | delayed_15 | avg_taxi_min | nas | carrier | weather | late_aircraft | security |
|---|---|---|---|---|---|---|---|---|---|---|---|
| JFK | 1 | dep | 7 (F1–F5, F12, F14) | 1 | 2 (F3, F12) | 159 / 6 = 26.5 | NULL | NULL | NULL | NULL | NULL |
| BOS | 1 | dep | 3 (F6, F7, F15) | 1 | 0 | 45 / 2 = 22.5 | NULL | NULL | NULL | NULL | NULL |
| LAX | 1 | dep | 3 (F8, F9, F10) | 0 | 1 (F10) | 54 / 3 = 18 | NULL | NULL | NULL | NULL | NULL |
| DJT | 1 | dep | 1 (F13) | 0 | 0 | 16 | NULL | NULL | NULL | NULL | NULL |
| LAX | 1 | arr | 5 (F1–F4, F15) | 1 | 1 (F3) | 34 / 4 = 8.5 | 20 | 100 | 0 | 0 | 0 |
| BOS | 1 | arr | 2 (F5, F10) | 0 | 1 (F10) | 11 / 2 = 5.5 | 10 | 0 | 50 | 15 | 5 |
| JFK | 1 | arr | 6 (F6–F9, F11, F13) | 1 | 1 (F6) | 60 / 5 = 12 | 30 | 0 | 0 | 0 | 0 |
| DJT | 1 | arr | 1 (F14) | 0 | 1 | 6 | 0 | 0 | 0 | 40 | 0 |
| JFK | 2 | dep | 5 (F16–F18, F22, F23) | 2 | 2 (F18, F22) | 90 / 3 = 30 | NULL | NULL | NULL | NULL | NULL |
| LAX | 2 | dep | 3 (F19, F20, F28) | 1 | 0 | 32 / 2 = 16 | NULL | NULL | NULL | NULL | NULL |
| BOS | 2 | dep | 3 (F21, F26, F27) | 1 | 1 (F27) | 49 / 2 = 24.5 | NULL | NULL | NULL | NULL | NULL |
| DJT | 2 | dep | 1 (F25) | 0 | 0 | 14 | NULL | NULL | NULL | NULL | NULL |
| LAX | 2 | arr | 4 (F16–F18, F27) | 1 | 2 (F18, F27) | 30 / 3 = 10 | 60 | 45 | 0 | 30 | 0 |
| JFK | 2 | arr | 5 (F19–F21, F24, F28) | 1 | 1 (F24) | 47 / 4 = 11.75 | 0 | 0 | 25 | 0 | 0 |
| BOS | 2 | arr | 3 (F22, F23, F25) | 1 | 0 | 11 / 2 = 5.5 | 0 | 0 | 0 | 0 | 0 |
| DJT | 2 | arr | 1 (F26) | 1 | 0 | NULL (only a cancelled flight) | 0 | 0 | 0 | 0 | 0 |

**Hand-worked totals:**
- Flights: dep 26 (28 − F11, F24 from PSE), arr 27 (28 − F12 to PSE), all rows **53**. January 28, February 25.
- Cancelled: 6 flights (F4, F7, F17, F23, F26, F28), each on a dep and an arr row = **12**.
- Delayed 15+: dep **6** (F3, F10, F12, F18, F22, F27); arr **7** (F3, F6, F10, F14, F18, F24, F27; F12 went to PSE).
- Cause minutes, all rows: NAS **120**, carrier **145** (F12's 60 is dropped with PSE), weather **75**, late aircraft **85**, security **5**.
- Cancelled flights skipped in taxi averages: counting F4 as 0 would give JFK Jan dep 159 / 7 = 22.71 instead of 26.5. The diverted F9 counts: JFK Jan arr 60 / 5 = 12 (without it 45 / 4 = 11.25).

Other zips are built in `tmp_path` with the same writer: one with `readme.html` first (same 16 rows), January and February as two single-month zips (the same table as the combined sample), and one with the `NASDelay` column missing (must fail and leave the table unchanged).
