# Lanka Weather

A weather website for Sri Lanka: 25 districts and popular towns, live forecasts, island heat map, 10-day outlook, air quality, sea conditions, and English / Sinhala / Tamil.

Live data comes from [Open-Meteo](https://open-meteo.com) (no API key needed). The whole site is a single `index.html` file.

Forecasts are model-based and not official warnings. For official warnings see the Department of Meteorology (meteo.gov.lk) and NBRO (nbro.gov.lk).

## Official notices

Notices from the Navy, Department of Meteorology and others are shown from `notices.json`. To add one, open `add-notice.html` on the live site, fill the form, and paste the result into `notices.json` on GitHub. Each notice can target the whole island, all coastal places, a province, or chosen districts and towns, and can expire automatically.
