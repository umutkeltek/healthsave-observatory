"""Lab result CSV normalization — pure, deterministic (Labs slice 1).

Turns a lab CSV (template: ``docs/capture/labs-csv.md``) into normalized lab
results that map onto the canonical observation shape:

* ``metric_id`` = ``loinc:<code>``; the LOINC check digit is validated.
* the value and the lab's own reference range are converted to one canonical
  UCUM unit per known marker, **only** within one dimension (mass/volume,
  moles/volume, counts, enzyme units, fractions). Molar and mass units are
  never converted into each other: LOINC gives them different codes.
* identity follows the Source/Device/Stream model: Source = the ``labs-csv``
  integration, Device = the performing lab, Stream = that lab via that
  integration (``normalization.identity.stream_id``). The panel is an attribute.

The whole file is validated before anything is returned. Any invalid row raises
:class:`LabCsvValidationError` carrying every problem found: a deterministic
"422-class" rejection — retrying the same file gives the same answer.

No DB, no network, no clock (``now`` is passed in).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid5

from . import identity

LABS_CSV_PLUGIN = "labs-csv"
NORMALIZER_ID = "labs-csv"
NORMALIZER_VERSION = "1"
METRIC_PREFIX = "loinc:"
MAX_ROWS = 10_000

REQUIRED_COLUMNS = ("specimen_datetime", "loinc", "value", "unit", "lab")
OPTIONAL_COLUMNS = ("marker_name", "reference_low", "reference_high", "panel")
KNOWN_COLUMNS = frozenset(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)

FLAG_DATE_ONLY = "date_only"
FLAG_UNIT_UNRECONCILED = "unit_unreconciled"
FLAG_CENSORED = "censored"

# ──────────────────────────────────────────────────────────────────
# LOINC
# ──────────────────────────────────────────────────────────────────

_LOINC_RE = re.compile(r"^(\d{1,7})-(\d)$")


def loinc_check_digit(body: str) -> int:
    """Mod-10 check digit LOINC uses (Luhn over the code body)."""
    total = 0
    for position, char in enumerate(reversed(body)):
        digit = int(char)
        if position % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return (10 - total % 10) % 10


def is_valid_loinc(code: str) -> bool:
    match = _LOINC_RE.match(code)
    return bool(match) and loinc_check_digit(match.group(1)) == int(match.group(2))


def metric_id_for(loinc_code: str) -> str:
    return f"{METRIC_PREFIX}{loinc_code}"


# ──────────────────────────────────────────────────────────────────
# UCUM (small on purpose)
# ──────────────────────────────────────────────────────────────────

# Case-sensitive spellings first: German reports write giga/tera per litre as
# "G/L" / "T/L", which must not collide with grams per litre ("g/L").
_CASE_SENSITIVE_UNITS = {
    "G/L": "10*9/L",
    "T/L": "10*12/L",
    "/nL": "10*9/L",
    "/pL": "10*12/L",
}

# Case-insensitive spellings → UCUM code.
_UNIT_ALIASES = {
    "g/dl": "g/dL",
    "g/l": "g/L",
    "mg/dl": "mg/dL",
    "mg/l": "mg/L",
    "ug/dl": "ug/dL",
    "µg/dl": "ug/dL",
    "μg/dl": "ug/dL",
    "mcg/dl": "ug/dL",
    "ug/l": "ug/L",
    "µg/l": "ug/L",
    "μg/l": "ug/L",
    "mcg/l": "ug/L",
    "ng/ml": "ng/mL",
    "ng/dl": "ng/dL",
    "ng/l": "ng/L",
    "pg/ml": "pg/mL",
    "mmol/l": "mmol/L",
    "umol/l": "umol/L",
    "µmol/l": "umol/L",
    "μmol/l": "umol/L",
    "nmol/l": "nmol/L",
    "pmol/l": "pmol/L",
    "mmol/mol": "mmol/mol",
    "%": "%",
    "l/l": "L/L",
    "u/l": "U/L",
    "iu/l": "U/L",
    "miu/l": "m[IU]/L",
    "mu/l": "m[IU]/L",
    "mui/l": "m[IU]/L",
    "uiu/ml": "u[IU]/mL",
    "µiu/ml": "u[IU]/mL",
    "μiu/ml": "u[IU]/mL",
    "µu/ml": "u[IU]/mL",
    "uu/ml": "u[IU]/mL",
    "10^9/l": "10*9/L",
    "10*9/l": "10*9/L",
    "x10^9/l": "10*9/L",
    "x10e9/l": "10*9/L",
    "10^12/l": "10*12/L",
    "10*12/l": "10*12/L",
    "x10^12/l": "10*12/L",
    "x10e12/l": "10*12/L",
    "10^3/ul": "10*3/uL",
    "10*3/ul": "10*3/uL",
    "x10^3/ul": "10*3/uL",
    "10^3/µl": "10*3/uL",
    "k/ul": "10*3/uL",
    "10^6/ul": "10*6/uL",
    "10*6/ul": "10*6/uL",
    "x10^6/ul": "10*6/uL",
    "10^6/µl": "10*6/uL",
    "m/ul": "10*6/uL",
    "fl": "fL",
    "pg": "pg",
}

# Same-dimension factors to one base unit per dimension. A conversion exists
# only between two units of the SAME dimension: factor = base[from] / base[to].
_DIMENSIONS: dict[str, dict[str, float]] = {
    "mass_concentration": {  # base g/L
        "g/L": 1.0,
        "g/dL": 10.0,
        "mg/dL": 1e-2,
        "mg/L": 1e-3,
        "ug/dL": 1e-5,
        "ug/L": 1e-6,
        "ng/mL": 1e-6,
        "ng/dL": 1e-8,
        "ng/L": 1e-9,
        "pg/mL": 1e-9,
    },
    "substance_concentration": {  # base mol/L
        "mmol/L": 1e-3,
        "umol/L": 1e-6,
        "nmol/L": 1e-9,
        "pmol/L": 1e-12,
    },
    "number_concentration": {  # base 1/L
        "10*9/L": 1e9,
        "10*3/uL": 1e9,
        "10*12/L": 1e12,
        "10*6/uL": 1e12,
    },
    "catalytic_concentration": {"U/L": 1.0},
    "arbitrary_concentration": {"m[IU]/L": 1.0, "u[IU]/mL": 1.0},
    "fraction": {"%": 0.01, "L/L": 1.0},
    "substance_ratio": {"mmol/mol": 1.0},
    "volume": {"fL": 1.0},
    "mass": {"pg": 1.0},
}
_DIMENSION_OF = {unit: dim for dim, units in _DIMENSIONS.items() for unit in units}

_DISPLAY_UNITS = {
    "10*9/L": "×10⁹/L",
    "10*12/L": "×10¹²/L",
    "10*3/uL": "×10³/µL",
    "10*6/uL": "×10⁶/µL",
    "m[IU]/L": "mIU/L",
    "u[IU]/mL": "µIU/mL",
    "ug/dL": "µg/dL",
    "ug/L": "µg/L",
    "umol/L": "µmol/L",
}


def normalize_unit(raw: str) -> str | None:
    """UCUM code for a known spelling, else ``None``."""
    spelled = " ".join(raw.strip().split())
    if spelled in _CASE_SENSITIVE_UNITS:
        return _CASE_SENSITIVE_UNITS[spelled]
    return _UNIT_ALIASES.get(spelled.lower())


def unit_dimension(ucum: str) -> str | None:
    return _DIMENSION_OF.get(ucum)


def conversion_factor(from_unit: str, to_unit: str) -> float | None:
    """Multiplier from ``from_unit`` to ``to_unit``; ``None`` across dimensions."""
    if from_unit == to_unit:
        return 1.0
    dim = _DIMENSION_OF.get(from_unit)
    if dim is None or dim != _DIMENSION_OF.get(to_unit):
        return None
    table = _DIMENSIONS[dim]
    return table[from_unit] / table[to_unit]


def display_unit(ucum: str) -> str:
    """Human spelling for a UCUM code (µ, ×10ⁿ, IU without brackets)."""
    return _DISPLAY_UNITS.get(ucum, ucum)


# ──────────────────────────────────────────────────────────────────
# Marker catalog (a starting set; unknown LOINC codes are still accepted)
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MarkerInfo:
    loinc: str
    name: str
    canonical_unit: str


_CATALOG: tuple[MarkerInfo, ...] = (
    MarkerInfo("718-7", "Hemoglobin", "g/dL"),
    MarkerInfo("4544-3", "Hematocrit", "%"),
    MarkerInfo("789-8", "Red blood cells", "10*12/L"),
    MarkerInfo("6690-2", "White blood cells", "10*9/L"),
    MarkerInfo("777-3", "Platelets", "10*9/L"),
    MarkerInfo("2276-4", "Ferritin", "ng/mL"),
    MarkerInfo("2498-4", "Iron", "ug/dL"),
    MarkerInfo("2132-9", "Vitamin B12", "pg/mL"),
    MarkerInfo("1989-3", "Vitamin D (25-OH)", "ng/mL"),
    MarkerInfo("4548-4", "HbA1c (NGSP)", "%"),
    MarkerInfo("59261-8", "HbA1c (IFCC)", "mmol/mol"),
    MarkerInfo("2345-7", "Glucose", "mg/dL"),
    MarkerInfo("14749-6", "Glucose (molar)", "mmol/L"),
    MarkerInfo("2093-3", "Total cholesterol", "mg/dL"),
    MarkerInfo("2085-9", "HDL cholesterol", "mg/dL"),
    MarkerInfo("13457-7", "LDL cholesterol (calculated)", "mg/dL"),
    MarkerInfo("2571-8", "Triglycerides", "mg/dL"),
    MarkerInfo("3016-3", "TSH", "m[IU]/L"),
    MarkerInfo("3024-7", "Free T4", "ng/dL"),
    MarkerInfo("2160-0", "Creatinine", "mg/dL"),
    MarkerInfo("1988-5", "CRP", "mg/L"),
    MarkerInfo("1742-6", "ALT", "U/L"),
    MarkerInfo("1920-8", "AST", "U/L"),
)
MARKER_CATALOG: dict[str, MarkerInfo] = {marker.loinc: marker for marker in _CATALOG}


def marker_display_name(loinc_code: str, given: str | None = None) -> str:
    """Catalog name, else the name printed in the file, else ``LOINC <code>``."""
    known = MARKER_CATALOG.get(loinc_code)
    if known is not None:
        return known.name
    if given and given.strip():
        return given.strip()
    return f"LOINC {loinc_code}"


# ──────────────────────────────────────────────────────────────────
# Result + error types
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NormalizedLabResult:
    """One validated result, field-for-field what ``lab_results`` stores."""

    id: UUID
    metric_id: str
    loinc_code: str
    marker_name: str | None
    numeric_value: float
    value_comparator: str | None
    canonical_unit: str
    reference_low: float | None
    reference_high: float | None
    reference_text: str | None
    specimen_at: datetime
    lab_name: str
    panel: str | None
    source_id: UUID
    source_plugin_id: str
    stream_id: UUID
    dedup_key: str
    semantic_key: str | None
    normalizer_id: str
    normalizer_version: str
    quality_flags: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LabRowError:
    """One problem: the file row (1 = header), the column, and what to fix."""

    row: int
    column: str | None
    message: str

    def __str__(self) -> str:
        where = f"row {self.row}" if self.row else "file"
        if self.column:
            where += f", column {self.column}"
        return f"{where}: {self.message}"


class LabCsvValidationError(ValueError):
    """The file was rejected; nothing may be written.

    Deterministic (the 422 class): the same file always fails the same way, so
    callers must not retry it — they report ``errors`` and stop.
    """

    status_code = 422
    retryable = False

    def __init__(self, errors: list[LabRowError]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} problem(s) in the lab file")


@dataclass(frozen=True, slots=True)
class LabCsvParse:
    results: list[NormalizedLabResult]
    file_sha256: str
    rows_read: int
    duplicates_collapsed: int


# ──────────────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────────────

_COMPARATORS = (("<=", "<="), (">=", ">="), ("≤", "<="), ("≥", ">="), ("<", "<"), (">", ">"))
_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d+$")
# "1,250" is one thousand two hundred and fifty on a US report and 1.25 on a
# German one. The shape cannot say which, so it is never parsed: reading it as a
# decimal once stored ferritin 1,250 ng/mL as 1.25, "below" its range.
_AMBIGUOUS_GROUPING = re.compile(r"^[+-]?[1-9]\d{0,2},\d{3}$")


def _number_problem(raw: str, otherwise: str) -> str:
    """Why a cell is not a number, naming both readings when it is the ambiguous shape."""
    text = raw.strip()
    for prefix, _ in _COMPARATORS:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if not _AMBIGUOUS_GROUPING.match(text):
        return f"{raw!r} {otherwise}"
    digits = text.lstrip("+-")
    return (
        f"{raw!r} could be {digits.replace(',', '')} or {digits.replace(',', '.')}; "
        "write it without a thousands separator"
    )


def _parse_number(raw: str) -> float | None:
    text = raw.strip()
    if _AMBIGUOUS_GROUPING.match(text):
        return None
    if _DECIMAL_COMMA.match(text):
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _parse_value(raw: str) -> tuple[float | None, str | None]:
    text = raw.strip()
    for prefix, comparator in _COMPARATORS:
        if text.startswith(prefix):
            return _parse_number(text[len(prefix) :]), comparator
    return _parse_number(text), None


def _parse_specimen(raw: str) -> tuple[datetime | None, bool, str | None]:
    """(instant, date_only, error)."""
    text = raw.strip()
    if not text:
        return None, False, "is empty"
    if len(text) == 10:
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None, False, f"{text!r} is not a date (use YYYY-MM-DD)"
        return datetime(day.year, day.month, day.day, tzinfo=UTC), True, None
    try:
        instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, False, f"{text!r} is not an ISO 8601 date or datetime"
    if instant.tzinfo is None or instant.utcoffset() is None:
        return (
            None,
            False,
            (
                f"{text!r} has no UTC offset; add one (for example +01:00 or Z) "
                "or give the date only"
            ),
        )
    return instant.astimezone(UTC), False, None


def _sha256(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        return data.lstrip("﻿")
    return data.decode("utf-8-sig")


def _delimiter(header_line: str) -> str:
    if header_line.count(";") > header_line.count(","):
        return ";"
    if header_line.count("\t") > header_line.count(","):
        return "\t"
    return ","


def _fmt(value: float) -> str:
    return f"{value:g}"


# ──────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────


def parse_lab_csv(
    data: bytes | str,
    *,
    owner_id: UUID,
    now: datetime,
    file_name: str = "labs.csv",
    plugin_id: str = LABS_CSV_PLUGIN,
) -> LabCsvParse:
    """Validate and normalize a whole lab CSV, or raise with every problem."""
    raw_bytes = data.encode() if isinstance(data, str) else data
    file_sha = hashlib.sha256(raw_bytes).hexdigest()
    try:
        text = _decode(data)
    except UnicodeDecodeError:
        raise LabCsvValidationError(
            [LabRowError(0, None, "the file is not UTF-8 text; save it as CSV UTF-8")]
        ) from None

    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise LabCsvValidationError([LabRowError(1, None, "the file is empty; expected a header")])

    reader = csv.DictReader(io.StringIO(text), delimiter=_delimiter(lines[0]))
    header = [(_clean(name)).lower() for name in (reader.fieldnames or [])]
    reader.fieldnames = header
    header_errors = [
        LabRowError(1, column, "required column is missing")
        for column in REQUIRED_COLUMNS
        if column not in header
    ]
    header_errors += [
        LabRowError(1, column or "(blank)", "unknown column; see docs/capture/labs-csv.md")
        for column in header
        if column not in KNOWN_COLUMNS
    ]
    if header_errors:
        raise LabCsvValidationError(header_errors)

    errors: list[LabRowError] = []
    results: list[NormalizedLabResult] = []
    seen: dict[str, tuple[int, NormalizedLabResult]] = {}
    duplicates = 0
    rows_read = 0
    source_id = identity.source_uuid(owner_id, plugin_id)

    for record in reader:
        row_number = reader.line_num
        if record.get(None):  # more cells than header columns
            errors.append(LabRowError(row_number, None, "more cells than header columns"))
            continue
        cells = {key: _clean(value) for key, value in record.items() if key}
        if not any(cells.values()):
            continue  # blank line
        rows_read += 1
        if rows_read > MAX_ROWS:
            errors.append(LabRowError(row_number, None, f"more than {MAX_ROWS} rows; split it"))
            break
        result, row_errors = _normalize_row(
            row_number,
            cells,
            owner_id=owner_id,
            source_id=source_id,
            plugin_id=plugin_id,
            now=now,
            file_name=file_name,
            file_sha=file_sha,
        )
        if row_errors:
            errors.extend(row_errors)
            continue
        assert result is not None
        earlier = seen.get(result.dedup_key)
        if earlier is None:
            seen[result.dedup_key] = (row_number, result)
            results.append(result)
            continue
        first_row, first = earlier
        same = (
            first.numeric_value == result.numeric_value
            and first.value_comparator == result.value_comparator
            and first.canonical_unit == result.canonical_unit
        )
        if same:
            duplicates += 1
            continue
        errors.append(
            LabRowError(
                row_number,
                "value",
                f"conflicts with row {first_row}: same lab, LOINC and specimen time, "
                "different value; keep one",
            )
        )

    if errors:
        raise LabCsvValidationError(errors)
    if not results:
        raise LabCsvValidationError([LabRowError(0, None, "no result rows after the header")])
    return LabCsvParse(
        results=results,
        file_sha256=file_sha,
        rows_read=rows_read,
        duplicates_collapsed=duplicates,
    )


def _normalize_row(
    row: int,
    cells: dict[str, str],
    *,
    owner_id: UUID,
    source_id: UUID,
    plugin_id: str,
    now: datetime,
    file_name: str,
    file_sha: str,
) -> tuple[NormalizedLabResult | None, list[LabRowError]]:
    errors: list[LabRowError] = []
    flags: list[str] = []

    loinc = cells.get("loinc", "")
    if not loinc:
        errors.append(LabRowError(row, "loinc", "is empty"))
    elif not _LOINC_RE.match(loinc):
        errors.append(LabRowError(row, "loinc", f"{loinc!r} is not a LOINC code (like 2276-4)"))
    elif not is_valid_loinc(loinc):
        errors.append(
            LabRowError(row, "loinc", f"{loinc!r} fails the LOINC check digit; check for a typo")
        )

    specimen_at, date_only, specimen_error = _parse_specimen(cells.get("specimen_datetime", ""))
    if specimen_error:
        errors.append(LabRowError(row, "specimen_datetime", specimen_error))
    elif specimen_at is not None and specimen_at > now:
        errors.append(LabRowError(row, "specimen_datetime", "is in the future"))
    if date_only:
        flags.append(FLAG_DATE_ONLY)

    raw_value = cells.get("value", "")
    value, comparator = _parse_value(raw_value)
    if not raw_value:
        errors.append(LabRowError(row, "value", "is empty"))
    elif value is None:
        errors.append(
            LabRowError(
                row,
                "value",
                _number_problem(raw_value, "is not a number (text results come later)"),
            )
        )
    if comparator:
        flags.append(FLAG_CENSORED)

    lab = " ".join(cells.get("lab", "").split())
    if not lab:
        errors.append(LabRowError(row, "lab", "is empty; name the lab that ran the test"))

    raw_unit = cells.get("unit", "")
    low_raw, high_raw = cells.get("reference_low", ""), cells.get("reference_high", "")
    low = _parse_number(low_raw) if low_raw else None
    high = _parse_number(high_raw) if high_raw else None
    if low_raw and low is None:
        errors.append(
            LabRowError(row, "reference_low", _number_problem(low_raw, "is not a number"))
        )
    if high_raw and high is None:
        errors.append(
            LabRowError(row, "reference_high", _number_problem(high_raw, "is not a number"))
        )
    if low is not None and high is not None and low > high:
        errors.append(LabRowError(row, "reference_low", "is above reference_high"))

    canonical_unit: str | None = None
    factor = 1.0
    if not raw_unit:
        errors.append(LabRowError(row, "unit", "is empty (use 1 for a unitless ratio)"))
    else:
        ucum = normalize_unit(raw_unit) or ("1" if raw_unit.strip() == "1" else None)
        marker = MARKER_CATALOG.get(loinc)
        if ucum is None:
            canonical_unit = " ".join(raw_unit.split())
            flags.append(FLAG_UNIT_UNRECONCILED)
        elif marker is None:
            canonical_unit = ucum
        else:
            converted = conversion_factor(ucum, marker.canonical_unit)
            if converted is None:
                errors.append(
                    LabRowError(
                        row,
                        "unit",
                        f"{raw_unit!r} does not fit {loinc} ({marker.name}, measured in "
                        f"{display_unit(marker.canonical_unit)}); molar and mass results have "
                        "different LOINC codes",
                    )
                )
            else:
                canonical_unit = marker.canonical_unit
                factor = converted

    if errors:
        return None, errors
    assert specimen_at is not None and value is not None and canonical_unit is not None

    origin = identity.normalize_origin(lab)
    stream_id = identity.stream_id(owner_id, plugin_id, origin)
    specimen_iso = specimen_at.isoformat()
    canonical_value = value * factor
    dedup_key = _sha256("labs:v1", stream_id, loinc, specimen_iso)
    semantic_key = _sha256(
        "labs-semantic:v1",
        owner_id,
        origin,
        loinc,
        specimen_iso,
        _fmt(canonical_value),
        canonical_unit,
    )
    reference_text = None
    if low_raw or high_raw:
        reference_text = f"{low_raw or ''}-{high_raw or ''} {raw_unit}".strip()
    given_name = cells.get("marker_name") or None
    result = NormalizedLabResult(
        id=uuid5(identity.STREAM_NAMESPACE, f"lab-result:{owner_id}:{dedup_key}"),
        metric_id=metric_id_for(loinc),
        loinc_code=loinc,
        marker_name=marker_display_name(loinc, given_name),
        numeric_value=canonical_value,
        value_comparator=comparator,
        canonical_unit=canonical_unit,
        reference_low=None if low is None else low * factor,
        reference_high=None if high is None else high * factor,
        reference_text=reference_text,
        specimen_at=specimen_at,
        lab_name=lab,
        panel=cells.get("panel") or None,
        source_id=source_id,
        source_plugin_id=plugin_id,
        stream_id=stream_id,
        dedup_key=dedup_key,
        semantic_key=semantic_key,
        normalizer_id=NORMALIZER_ID,
        normalizer_version=NORMALIZER_VERSION,
        quality_flags=tuple(flags),
        provenance={
            "file_name": file_name,
            "file_sha256": file_sha,
            "row": row,
            "raw_value": raw_value,
            "raw_unit": raw_unit,
            "marker_name_as_written": given_name,
            "conversion_factor": factor,
        },
    )
    return result, []


__all__ = [
    "FLAG_CENSORED",
    "FLAG_DATE_ONLY",
    "FLAG_UNIT_UNRECONCILED",
    "LABS_CSV_PLUGIN",
    "MARKER_CATALOG",
    "LabCsvParse",
    "LabCsvValidationError",
    "LabRowError",
    "MarkerInfo",
    "NormalizedLabResult",
    "conversion_factor",
    "display_unit",
    "is_valid_loinc",
    "loinc_check_digit",
    "marker_display_name",
    "metric_id_for",
    "normalize_unit",
    "parse_lab_csv",
    "unit_dimension",
]
