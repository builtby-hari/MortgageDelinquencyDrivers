# Scenario Files

## fed_2026.csv

The Federal Reserve's final 2026 supervisory stress test scenarios, baseline and severely adverse. The Fed publishes no adverse scenario in this set.

- **Source:** https://www.federalreserve.gov/publications/2026-stress-test-scenarios.htm, Table 3.A (supervisory baseline, domestic variables) and Table 4.A (supervisory severely adverse, domestic variables). Final notice PDF: https://www.federalreserve.gov/publications/files/2026-final-supervisory-stress-test-scenarios-20260204.pdf
- **Dates:** the final scenarios are dated February 4, 2026 (from the PDF name); the web page shows Last Update February 17, 2026. The page was read on 2026-10-21.
- **Variables used:** "Unemployment rate" (percent) and "Mortgage rate" (the Fed's 30-year fixed mortgage rate, percent), both quarterly levels as printed to one decimal. The Fed tables are on the page as HTML, not as a CSV download, so these values were copied from the tables.
- **Quarters:** the Fed paths run 2026Q1 to 2029Q1. The file keeps 2026Q2 (an anchor row) and 2026Q3 to 2028Q3, the 9 quarters the tool projects. Other quarters are dropped.
- **Alignment:** the Fed's jump-off is 2026Q1, and its 2026Q2 values differ from the data here (baseline unemployment 4.6 against 4.3 observed; severely adverse 7.2). Run as is, the Fed levels are used exactly as published, which makes the severely adverse path jump from 4.3% observed to 8.2% in one quarter. With `--rebase`, each scenario is shifted by observed minus the file's 2026Q2 row, so it starts at the observed levels and keeps the Fed's changes.
