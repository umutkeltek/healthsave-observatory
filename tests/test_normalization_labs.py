"""Lab CSV normalization: LOINC, UCUM, identity, and 422-class validation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from normalization import identity
from normalization.labs import (
    FLAG_CENSORED,
    FLAG_DATE_ONLY,
    FLAG_UNIT_UNRECONCILED,
    LABS_CSV_PLUGIN,
    MARKER_CATALOG,
    LabCsvValidationError,
    conversion_factor,
    display_unit,
    is_valid_loinc,
    loinc_check_digit,
    normalize_unit,
    parse_lab_csv,
    unit_dimension,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "labs" / "sample_labs.csv"
OWNER = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
HEADER = "specimen_datetime,loinc,value,unit,reference_low,reference_high,lab\n"


def _parse(text: str):
    return parse_lab_csv(text, owner_id=OWNER, now=NOW, file_name="t.csv")


def _errors(text: str) -> list[str]:
    with pytest.raises(LabCsvValidationError) as caught:
        _parse(text)
    return [str(problem) for problem in caught.value.errors]


# ── LOINC ─────────────────────────────────────────────────────────


def test_loinc_check_digit_matches_published_codes() -> None:
    assert loinc_check_digit("718") == 7
    assert loinc_check_digit("2276") == 4
    assert loinc_check_digit("4548") == 4
    assert is_valid_loinc("59261-8")
    assert not is_valid_loinc("2276-5")
    assert not is_valid_loinc("2276")
    assert not is_valid_loinc("abc-1")


def test_every_catalog_code_passes_the_check_digit() -> None:
    bad = [code for code in MARKER_CATALOG if not is_valid_loinc(code)]
    assert not bad, f"catalog has LOINC typos: {bad}"


def test_every_catalog_unit_is_a_known_ucum_dimension() -> None:
    unknown = [m.loinc for m in MARKER_CATALOG.values() if unit_dimension(m.canonical_unit) is None]
    assert not unknown, f"catalog units outside the UCUM table: {unknown}"


# ── UCUM ──────────────────────────────────────────────────────────


def test_unit_spellings_normalize_and_giga_is_not_grams() -> None:
    assert normalize_unit("mg/dl") == "mg/dL"
    assert normalize_unit("µg/L") == "ug/L"
    assert normalize_unit("mcg/l") == "ug/L"
    assert normalize_unit("G/L") == "10*9/L"
    assert normalize_unit("g/L") == "g/L"
    assert normalize_unit("x10^9/L") == "10*9/L"
    assert normalize_unit("µIU/mL") == "u[IU]/mL"
    assert normalize_unit("furlongs") is None


def test_conversion_only_within_one_dimension() -> None:
    assert conversion_factor("g/L", "g/dL") == pytest.approx(0.1)
    assert conversion_factor("ug/L", "ng/mL") == pytest.approx(1.0)
    assert conversion_factor("10*3/uL", "10*9/L") == pytest.approx(1.0)
    assert conversion_factor("L/L", "%") == pytest.approx(100.0)
    assert conversion_factor("mmol/L", "mg/dL") is None  # molar vs mass: never
    assert conversion_factor("%", "mmol/mol") is None  # HbA1c NGSP vs IFCC: never


def test_display_units_are_human() -> None:
    assert display_unit("10*9/L") == "×10⁹/L"
    assert display_unit("m[IU]/L") == "mIU/L"
    assert display_unit("ug/L") == "µg/L"
    assert display_unit("ng/mL") == "ng/mL"


# ── The synthetic sample ──────────────────────────────────────────


def test_sample_file_parses_into_canonical_results() -> None:
    parsed = parse_lab_csv(SAMPLE.read_bytes(), owner_id=OWNER, now=NOW, file_name=SAMPLE.name)
    results = parsed.results
    assert len(results) == 12
    assert {r.loinc_code for r in results} == {"2276-4", "718-7", "4548-4", "1988-5"}
    assert {r.lab_name for r in results} == {"Northfield Diagnostics", "Harbor Clinical Lab"}
    assert all(r.metric_id == f"loinc:{r.loinc_code}" for r in results)
    assert all(r.source_plugin_id == LABS_CSV_PLUGIN for r in results)
    assert all(r.source_id == identity.source_uuid(OWNER, LABS_CSV_PLUGIN) for r in results)


def test_sample_converts_value_and_reference_range_together() -> None:
    parsed = parse_lab_csv(SAMPLE.read_bytes(), owner_id=OWNER, now=NOW)
    harbor_hgb = next(
        r for r in parsed.results if r.loinc_code == "718-7" and r.lab_name == "Harbor Clinical Lab"
    )
    assert harbor_hgb.canonical_unit == "g/dL"
    assert harbor_hgb.numeric_value == pytest.approx(12.8)
    assert harbor_hgb.reference_low == pytest.approx(13.0)
    assert harbor_hgb.reference_high == pytest.approx(17.0)
    assert harbor_hgb.marker_name == "Hemoglobin"  # catalog name, not the spelling in the file
    assert harbor_hgb.provenance["raw_unit"] == "g/L"
    assert harbor_hgb.provenance["marker_name_as_written"] == "Haemoglobin"


def test_sample_times_flags_and_censoring() -> None:
    parsed = parse_lab_csv(SAMPLE.read_bytes(), owner_id=OWNER, now=NOW)
    by_key = {
        (r.loinc_code, r.specimen_at.date().isoformat(), r.lab_name): r for r in parsed.results
    }
    march = by_key[("2276-4", "2026-03-10", "Northfield Diagnostics")]
    assert march.specimen_at == datetime(2026, 3, 10, 7, 15, tzinfo=UTC)
    assert FLAG_DATE_ONLY not in march.quality_flags
    november = by_key[("2276-4", "2025-11-18", "Northfield Diagnostics")]
    assert FLAG_DATE_ONLY in november.quality_flags
    crp = by_key[("1988-5", "2026-03-10", "Northfield Diagnostics")]
    assert (crp.numeric_value, crp.value_comparator) == (0.5, "<")
    assert FLAG_CENSORED in crp.quality_flags
    assert crp.reference_low is None and crp.reference_high == 5.0


def test_identity_is_deterministic_and_per_lab() -> None:
    first = parse_lab_csv(SAMPLE.read_bytes(), owner_id=OWNER, now=NOW).results
    second = parse_lab_csv(SAMPLE.read_bytes(), owner_id=OWNER, now=NOW).results
    assert [r.id for r in first] == [r.id for r in second]
    assert [r.dedup_key for r in first] == [r.dedup_key for r in second]
    northfield = identity.stream_id(OWNER, LABS_CSV_PLUGIN, "northfield diagnostics")
    harbor = identity.stream_id(OWNER, LABS_CSV_PLUGIN, "harbor clinical lab")
    assert {r.stream_id for r in first} == {northfield, harbor}


def test_lab_name_spacing_and_case_do_not_split_a_stream() -> None:
    parsed = _parse(
        HEADER
        + "2026-01-02,2276-4,40,ng/mL,30,400,Northfield  Diagnostics\n"
        + "2026-02-02,2276-4,38,ng/mL,30,400,northfield diagnostics\n"
    )
    assert len({r.stream_id for r in parsed.results}) == 1


def test_semicolon_files_with_decimal_commas_parse() -> None:
    parsed = _parse(
        "specimen_datetime;loinc;value;unit;reference_low;reference_high;lab\n"
        "2026-01-02;718-7;13,9;g/dL;13,5;17,5;Labor Mitte\n"
    )
    (result,) = parsed.results
    assert result.numeric_value == pytest.approx(13.9)
    assert result.reference_low == pytest.approx(13.5)


def test_unknown_marker_keeps_its_own_unit_and_name() -> None:
    parsed = _parse(
        "specimen_datetime,loinc,marker_name,value,unit,lab\n"
        "2026-01-02,2951-2,Sodium,140,mmol/L,Northfield Diagnostics\n"
    )
    (result,) = parsed.results
    assert result.canonical_unit == "mmol/L"
    assert result.marker_name == "Sodium"
    assert FLAG_UNIT_UNRECONCILED not in result.quality_flags


def test_unknown_unit_spelling_is_kept_and_flagged() -> None:
    parsed = _parse(HEADER + "2026-01-02,2276-4,40,ng/cc,,,Northfield Diagnostics\n")
    (result,) = parsed.results
    assert result.canonical_unit == "ng/cc"
    assert FLAG_UNIT_UNRECONCILED in result.quality_flags


def test_identical_duplicate_rows_are_counted_once() -> None:
    row = "2026-01-02,2276-4,40,ng/mL,30,400,Northfield Diagnostics\n"
    parsed = _parse(HEADER + row + row)
    assert len(parsed.results) == 1
    assert parsed.duplicates_collapsed == 1


# ── Rejections (deterministic, the 422 class) ─────────────────────


def test_validation_error_is_422_class_and_not_retryable() -> None:
    with pytest.raises(LabCsvValidationError) as caught:
        _parse(HEADER + "2026-01-02,2276-5,40,ng/mL,30,400,Lab\n")
    assert caught.value.status_code == 422
    assert caught.value.retryable is False


def test_every_bad_row_is_reported_at_once() -> None:
    problems = _errors(
        HEADER
        + "2026-01-02,2276-5,40,ng/mL,30,400,Lab A\n"  # row 2: check digit
        + "2026-03-10 08:15,718-7,14,g/dL,13.5,17.5,Lab A\n"  # row 3: no offset
        + "2027-01-01,718-7,14,g/dL,13.5,17.5,Lab A\n"  # row 4: future
        + "2026-01-02,718-7,high,g/dL,13.5,17.5,Lab A\n"  # row 5: not a number
        + "2026-01-02,4548-4,5.4,,4,5.6,Lab A\n"  # row 6: no unit
        + "2026-01-02,4548-4,5.4,%,6,5.6,Lab A\n"  # row 7: low above high
        + "2026-01-02,2345-7,5.4,mmol/L,,,Lab A\n"  # row 8: molar unit on a mass code
        + "2026-01-02,2276-4,40,ng/mL,30,400,\n"  # row 9: no lab
        + "2026-01-02,22764,40,ng/mL,30,400,Lab A\n"  # row 10: not a LOINC shape
    )
    joined = "\n".join(problems)
    assert len(problems) == 9, joined
    assert "row 2, column loinc: '2276-5' fails the LOINC check digit" in joined
    assert "row 3, column specimen_datetime" in joined and "no UTC offset" in joined
    assert "row 4, column specimen_datetime: is in the future" in joined
    assert "row 5, column value" in joined
    assert "row 6, column unit: is empty" in joined
    assert "row 7, column reference_low: is above reference_high" in joined
    assert "row 8, column unit" in joined and "different LOINC codes" in joined
    assert "row 9, column lab: is empty" in joined
    assert "row 10, column loinc" in joined


def test_conflicting_duplicates_are_rejected() -> None:
    problems = _errors(
        HEADER
        + "2026-01-02,2276-4,40,ng/mL,30,400,Northfield Diagnostics\n"
        + "2026-01-02,2276-4,44,ng/mL,30,400,Northfield Diagnostics\n"
    )
    assert problems == [
        "row 3, column value: conflicts with row 2: same lab, LOINC and specimen time, "
        "different value; keep one"
    ]


def test_header_problems_are_rejected_before_rows() -> None:
    problems = _errors(
        "specimen_datetime,loinc,value,unit,reference_hgih\n2026-01-02,718-7,14,g/dL,17\n"
    )
    assert "row 1, column lab: required column is missing" in problems
    assert any("column reference_hgih: unknown column" in p for p in problems)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("", "the file is empty"),
        (HEADER, "no result rows after the header"),
        (b"\xff\xfe\x00bad", "not UTF-8"),
    ],
)
def test_empty_and_unreadable_files_are_rejected(data, expected) -> None:
    with pytest.raises(LabCsvValidationError) as caught:
        parse_lab_csv(data, owner_id=OWNER, now=NOW)
    assert expected in str(caught.value.errors[0])
