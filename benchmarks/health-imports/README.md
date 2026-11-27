# Health import engineering benchmark

This corpus measures selected extraction, normalization and reference-matching
behaviors. **It is not a clinical validation study or a diagnostic accuracy score.**
All cases are hand-authored synthetic inputs. No patient documents or real genetic
samples are included. Expected outputs in `cases.json` are fixed independently of
the implementation and must never be regenerated from parser output to make a test pass.

Run from the repository root with the development Python environment and local
Poppler (`pdfinfo`, `pdftotext`, `pdftoppm`) and Tesseract installed:

```sh
make benchmark-health-imports BENCHMARK_ARGS='--json /tmp/health-import-benchmark.json --markdown /tmp/health-import-benchmark.md'
```

CI installs these tools and keeps the JSON and Markdown reports as artifacts.
The required command exits unsuccessfully for failed cases or skipped PDF cases.
Reports include the corpus hash, engine versions, observed values, counts and source
references. The command makes no external calls and uses temporary synthetic files.

| Coverage | Cases | What is checked |
| --- | ---: | --- |
| Lab results | 25 | Fixed conversions, inclusive limits, lab-specific ranges, withholding unsupported interpretations, invalid units/codes/dates, numbers that could be a thousands group or a decimal are refused, never guessed |
| PDF extraction | 12 | Ten text PDFs and two raster-only scans, explicit codes, flags, conflicting identities, missing results, source location and mandatory review |
| Genetics | 13 | Exact assembly/allele matching, no-calls, filters, indel exclusions, source conflict and review status |

Missing or extra extracted rows fail the case. Field counts in the JSON describe
only fixed expected fields, not clinical sensitivity or specificity. A clean scan
is not representative of phone photography, handwriting or multilingual lab reports.
The genetic reference is a tiny synthetic ClinVar-shaped fixture; it does not
validate patient genotyping, penetrance, ancestry effects or clinical risk.

## External review packet

External clinical review has **not** been performed. Give a designated reviewer:

1. The exact commit, `cases.json`, this document and both generated reports.
2. `packages/py/normalization/labs.py` and
   `packages/py/analysis/statistical/lab_reports.py` for unit policy, range handling,
   result limits and interpretation wording.
3. `packages/py/analysis/statistical/genetics.py` and
   `packages/py/storage/clinvar_reference.py` for source matching and limitations.
4. The source links and access dates in the corpus. The ClinVar review-status page
   has a recorded access gap, not a claimed fresh verification.

Ask the reviewer to record each case as accepted, correction needed, or outside
their expertise; propose missing cases; and assess user-facing wording separately
from numerical correctness. Record reviewer qualifications, date, scope, version,
conflicts of interest and unresolved issues. Obtain permission before adding any
real reports; de-identification alone is not permission to publish health data.

Remaining evaluation needs include independently reviewed cases, diverse real
document layouts, non-English reports, reference-range contexts such as age and
pregnancy, and actual phone/file-picker/download acceptance. No benchmark result
removes the requirement that users verify extracted fields against the original.
