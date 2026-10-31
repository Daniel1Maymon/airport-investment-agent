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
