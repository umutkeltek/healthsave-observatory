import gzip
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from analysis.statistical.genetics import build_genetic_report, review_stars
from normalization.genotypes import parse_genotypes
from storage.clinvar_reference import ClinvarReferenceStore

REFERENCE = b"""##fileformat=VCFv4.2
##fileDate=2026-11-08
##reference=GRCh38
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
1\t10\t900001\tA\tG\t.\t.\tGENEINFO=DEMO:1;CLNSIG=Pathogenic;CLNDN=Synthetic_condition;CLNREVSTAT=reviewed_by_expert_panel
1\t11\t900002\tC\tT\t.\t.\tGENEINFO=DEMO:1;CLNSIG=Conflicting_classifications_of_pathogenicity;CLNDN=Synthetic_condition;CLNREVSTAT=criteria_provided,_conflicting_classifications;CLNSIGCONF=Pathogenic(1)|Benign(1)
1\t12\t900003\tG\tA\t.\t.\tCLNSIG=Uncertain_significance;CLNDN=Synthetic_condition;CLNREVSTAT=criteria_provided,_single_submitter
1\t13\t900004\tA\tAT\t.\t.\tCLNSIG=Pathogenic;CLNREVSTAT=reviewed_by_expert_panel
"""
GENOTYPES = b"""##fileformat=VCFv4.2
##reference=GRCh38
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTHETIC
1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1
1\t11\trs2\tC\tT\t.\tPASS\t.\tGT\t1/1
1\t12\trs3\tC\tA\t.\tPASS\t.\tGT\t0/1
1\t20\trs4\tT\tC\t.\tPASS\t.\tGT\t0/1
"""


def install_reference(tmp_path):
    source = tmp_path / "synthetic-reference.vcf.gz"
    source.write_bytes(gzip.compress(REFERENCE))
    store = ClinvarReferenceStore(tmp_path / "index")
    metadata = store.install(
        source, assembly="GRCh38", source_url="https://example.invalid/synthetic-reference"
    )
    return store, source, metadata


@pytest.fixture
def reference(tmp_path):
    return install_reference(tmp_path)


def test_exact_evidence_matching_keeps_conflicts_and_withholds_mismatched_reference(reference):
    store, _, _ = reference
    parsed = parse_genotypes(GENOTYPES, "synthetic.vcf", assembly="GRCh38", forward_strand=True)
    snapshot, records = store.lookup("GRCh38", [(p.chromosome, p.position) for p in parsed.loci])
    identifier = uuid4()
    report = build_genetic_report(
        document_id=identifier,
        file_name="synthetic.vcf",
        input_sha256="a" * 64,
        parsed=parsed,
        reference=snapshot,
        records=records,
        now=datetime(2026, 11, 11, tzinfo=UTC),
    )
    assert report.matched_loci == 2
    assert report.unmatched_loci == 2
    assert report.reference_mismatch_loci == 1
    assert [a.review_stars for a in report.annotations] == [3, 1]
    assert report.annotations[0].alternate_copies == 1
    assert report.annotations[1].alternate_copies == 2
    assert report.annotations[1].conflicting
    assert report.annotations[1].category == "conflicting"
    assert all(a.call_quality == "file_filter_pass" for a in report.annotations)
    assert any("not negative health results" in warning for warning in report.warnings)
    retry = build_genetic_report(
        document_id=identifier,
        file_name="synthetic.vcf",
        input_sha256="a" * 64,
        parsed=parsed,
        reference=snapshot,
        records=records,
        now=datetime(2026, 11, 12, tzinfo=UTC),
    )
    assert retry.id == report.id


def test_reference_only_and_no_call_do_not_produce_a_positive_variant_match(reference):
    store, _, _ = reference
    content = GENOTYPES.replace(b"0/1", b"0/0").replace(b"1/1", b"./.")
    parsed = parse_genotypes(content, "synthetic.vcf", assembly="GRCh38", forward_strand=True)
    snapshot, records = store.lookup("GRCh38", [(p.chromosome, p.position) for p in parsed.loci])
    report = build_genetic_report(
        document_id=uuid4(),
        file_name="synthetic.vcf",
        input_sha256="a" * 64,
        parsed=parsed,
        reference=snapshot,
        records=records,
        now=datetime.now(UTC),
    )
    assert report.matched_annotations == 0
    assert report.input_counts["no_calls"] == 1


def test_failed_reference_install_preserves_the_previous_index(reference):
    store, source, metadata = reference
    source.write_bytes(gzip.compress(REFERENCE.replace(b"GRCh38", b"GRCh37")))
    with pytest.raises(ValueError, match="mismatched"):
        store.install(
            source, assembly="GRCh38", source_url="https://example.invalid/synthetic-reference"
        )
    assert store.metadata("GRCh38") == metadata
    assert store.lookup("GRCh38", [("1", 10)])[1][0]["variation_id"] == "900001"
    assert not list(store.root.glob("reference-*.sqlite"))


@pytest.mark.parametrize(
    "status,stars",
    [
        ("practice_guideline", 4),
        ("reviewed_by_expert_panel", 3),
        ("criteria_provided,_multiple_submitters,_no_conflicts", 2),
        ("criteria_provided,_single_submitter", 1),
        ("no_assertion_criteria_provided", 0),
        ("unknown_future_status", 0),
    ],
)
def test_review_stars_preserve_source_review_semantics(status, stars):
    assert review_stars(status) == stars
