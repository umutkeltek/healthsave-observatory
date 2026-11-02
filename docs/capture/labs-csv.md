# Blood test results (CSV import)

Bring your blood test results into the Observatory next to your wearable data.
Each result keeps the reference range **your lab printed**, the time the sample
was taken, and which lab ran it. Results from different labs are kept apart and
never averaged.

The file is read on your machine and handed to the API container of your own
stack. It does not cross the network, and lab rows never leave the host.

> HealthSave Observatory shows your numbers against the lab's own range and your
> own history. It does not diagnose, name conditions, or give treatment advice.
> Talk to a clinician about what a result means for you.

## Import a file

```bash
healthsave labs import results.csv --dry-run   # check the file, write nothing
healthsave labs import results.csv             # import it
```

The stack must be running (`healthsave up`). Importing the same file again is
safe: unchanged rows stay as they are. If you correct a value in the file and
import it again, that result is updated and the import says so.

The whole file is checked before anything is written. If any row has a problem,
nothing is written and every problem is listed with its row and column:

```text
results.csv was rejected; nothing was written. Fix 2 problem(s) and run it again:
  row 4, column loinc: '2276-5' fails the LOINC check digit; check for a typo
  row 7, column specimen_datetime: '2026-03-10 08:15' has no UTC offset; add one (for example +01:00 or Z) or give the date only
```

| Exit code | Meaning |
|---|---|
| `0` | Imported (or the dry run passed). |
| `2` | Usage error (no file, unknown option). |
| `65` | The file was rejected. Nothing was written. Running it again unchanged gives the same answer. |
| `75` | The database could not be reached. Nothing was written. Safe to run again. |

## Template

A header row, then one result per row. Comma-separated (semicolons and tabs also
work), UTF-8. Column order does not matter; names are not case-sensitive.

```csv
specimen_datetime,loinc,marker_name,value,unit,reference_low,reference_high,lab,panel
2026-03-10T08:15:00+01:00,2276-4,Ferritin,41,ng/mL,30,400,Northfield Diagnostics,Iron studies
2026-03-10T08:15:00+01:00,718-7,Hemoglobin,14.1,g/dL,13.5,17.5,Northfield Diagnostics,Complete blood count
2026-03-10T08:15:00+01:00,1988-5,CRP,<0.5,mg/L,,5,Northfield Diagnostics,
2026-09-17,718-7,Haemoglobin,128,g/L,130,170,Harbor Clinical Lab,Full blood count
```

A longer synthetic example lives in
[`tests/fixtures/labs/sample_labs.csv`](../../tests/fixtures/labs/sample_labs.csv)
(invented values, not a real person).

| Column | Required | What to put |
|---|---|---|
| `specimen_datetime` | yes | When the sample was taken (not the report date). Either a date (`2026-09-17`) or a date and time **with** a UTC offset (`2026-03-10T08:15:00+01:00`, or `Z` for UTC). A time without an offset is rejected, because the same clock time means different moments in different places. |
| `loinc` | yes | The [LOINC](https://loinc.org) code of the test, like `2276-4` for ferritin. The check digit after the dash is verified, so a typo is caught. Many lab reports print the code; otherwise search loinc.org for the test name and unit. |
| `value` | yes | The number. A decimal comma (`4,5`) is accepted. A result printed as below or above a limit (`<0.5`, `>90`) is kept with its sign and never used to compute a change. Text results (`positive`) are not supported yet. |
| `unit` | yes | The unit as printed: `ng/mL`, `g/dL`, `g/L`, `mmol/L`, `%`, `10^9/L`, `G/L`, `mIU/L`, ... Use `1` for a unitless ratio. |
| `reference_low` | no | The low end of the range your lab printed for this result. |
| `reference_high` | no | The high end. Leave a side empty when the lab printed only one (like `<5`). |
| `lab` | yes | The lab that ran the test. Each lab becomes its own source stream, so its results and ranges stay together. |
| `marker_name` | no | The name as printed. Known markers use a standard name; for other codes this name is shown. |
| `panel` | no | The panel or order the test was part of (`Complete blood count`). Shown as a label only. |

Unknown columns are rejected, so a misspelled column name cannot silently drop
your reference range.

## Units

Units are written as [UCUM](https://ucum.org) codes. For a set of common markers
the Observatory stores one unit and converts the value **and** the reference
range when you give a unit of the same kind:

| Marker | LOINC | Stored in | Also accepted (converted) |
|---|---|---|---|
| Hemoglobin | 718-7 | g/dL | g/L |
| Ferritin | 2276-4 | ng/mL | µg/L |
| HbA1c (NGSP) | 4548-4 | % | |
| HbA1c (IFCC) | 59261-8 | mmol/mol | |
| Glucose | 2345-7 | mg/dL | g/L, mg/L |
| Glucose (molar) | 14749-6 | mmol/L | µmol/L |
| White blood cells, platelets | 6690-2, 777-3 | ×10⁹/L | ×10³/µL, G/L |
| TSH | 3016-3 | mIU/L | µIU/mL |

The full starting set (23 markers) is in `packages/py/normalization/labs.py`.

Mass and molar units are **not** converted into each other. LOINC gives them
different codes (glucose in mg/dL is `2345-7`, in mmol/L is `14749-6`), and the
conversion depends on the substance. If your unit does not fit the code you
gave, the row is rejected with a hint. For a code that is not in the starting
set, the value is stored in the unit you gave.

## What is not here yet

- Lab report PDFs, and clinical records from Apple Health.
- Entering a result by hand in the web app.
- Text results (`positive`, `trace`).
