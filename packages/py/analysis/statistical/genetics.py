"""Exact allele evidence retrieval, with no disease-risk inference or egress."""

from datetime import date, datetime
from uuid import UUID, uuid5

from contracts.genetics import GeneticAnnotation, GeneticReference, GeneticReport
from normalization.genotypes import GenotypeFile

ENGINE_VERSION = "genetic-evidence-1"
MAX_ANNOTATIONS = 15000


def review_stars(review_status: str) -> int:
    normalized = " ".join(review_status.replace("_", " ").lower().split())
    return {
        "practice guideline": 4,
        "reviewed by expert panel": 3,
        "criteria provided, multiple submitters, no conflicts": 2,
        "criteria provided, single submitter": 1,
        "criteria provided, conflicting classifications": 1,
        "criteria provided, conflicting interpretations": 1,
    }.get(normalized, 0)


def build_genetic_report(
    *,
    document_id: UUID,
    file_name: str,
    input_sha256: str,
    parsed: GenotypeFile,
    reference: dict,
    records: list[dict],
    now: datetime,
) -> GeneticReport:
    snapshot = GeneticReference.model_validate(reference)
    if snapshot.assembly != parsed.assembly:
        raise ValueError("The reference and genotype genome assemblies must match exactly.")
    loci = {(item.chromosome, item.position): item for item in parsed.loci}
    annotations = []
    matched = set()
    mismatches = set()
    matches = 0
    for record in records:
        key = record["chromosome"], record["position"]
        locus = loci.get(key)
        if not locus:
            continue
        if locus.reference is not None and locus.reference != record["reference"]:
            mismatches.add(key)
            continue
        alternate = record["alternate"]
        if alternate not in locus.alleles:
            continue
        matched.add(key)
        matches += 1
        if len(annotations) >= MAX_ANNOTATIONS:
            continue
        classification = record["classification"].replace("_", " ")
        review = record["review_status"].replace("_", " ")
        conflicting = (
            bool(record.get("conflicts"))
            or "conflicting" in classification.lower()
            or "conflicting" in review.lower()
        )
        category = (
            "conflicting"
            if conflicting
            else (
                "uncertain"
                if "uncertain" in classification.lower()
                else "pathogenic"
                if "pathogenic" in classification.lower()
                else "benign"
                if "benign" in classification.lower()
                else "other"
            )
        )
        identifier = record["variation_id"]
        if not str(identifier).isdigit():
            raise ValueError("The reference contains an invalid ClinVar identifier.")
        annotations.append(
            GeneticAnnotation(
                chromosome=locus.chromosome,
                position=locus.position,
                genotype="/".join(locus.alleles),
                reference=record["reference"],
                alternate=alternate,
                alternate_copies=locus.alleles.count(alternate),
                variation_id=identifier,
                gene=record.get("gene", "").replace("|", ", "),
                conditions=record.get("conditions", "").replace("_", " ").replace("|", "; "),
                source_classification=classification,
                source_review_status=review or "Not supplied",
                review_stars=review_stars(review),
                conflicting=conflicting,
                category=category,
                call_quality=locus.quality,
                depth=locus.depth,
                genotype_quality=locus.genotype_quality,
                hgvs=record.get("hgvs", ""),
                source_url=f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{identifier}/",
                details_truncated=record.get("details_truncated", False),
            )
        )
    warnings = list(parsed.warnings)
    if (now.date() - date.fromisoformat(snapshot.release_date)).days > 90:
        warnings.append(
            "This reference release is more than 90 days old. An update may change its annotations."
        )
    if matches > len(annotations):
        warnings.append(
            f"This report includes {len(annotations):,} of {matches:,} matched annotations. "
            "Use a smaller input file to inspect the omitted matches."
        )
    if mismatches:
        warnings.append(
            f"{len(mismatches):,} loci had a VCF reference allele mismatch "
            "and were not interpreted for those reference records."
        )
    report_id = uuid5(document_id, f"{ENGINE_VERSION}:{snapshot.index_version}:{snapshot.sha256}")
    return GeneticReport(
        id=report_id,
        document_id=document_id,
        created_at=now,
        engine_version=ENGINE_VERSION,
        file_name=file_name,
        input_sha256=input_sha256,
        input_format=parsed.format,
        assembly=parsed.assembly,
        assembly_in_file=parsed.assembly_in_file,
        input_counts=parsed.counts,
        reference=snapshot,
        annotations=annotations,
        matched_loci=len(matched),
        matched_annotations=matches,
        unmatched_loci=len(loci) - len(matched),
        reference_mismatch_loci=len(mismatches),
        omitted_annotations=matches - len(annotations),
        warnings=warnings,
        limitations=[
            "This is variant evidence retrieval, not a diagnosis, disease-risk estimate "
            "or validated clinical report.",
            "ClinVar classifications describe submitted evidence about a variant. They do not "
            "establish your phenotype, penetrance, inheritance pattern or a diagnosis.",
            "Review stars describe ClinVar review status, not the accuracy of your genotype "
            "or your personal health risk. Conflicting and uncertain evidence remains visible.",
            "Only exact assembly, position and alternate-allele matches are used. "
            "VCF reference alleles must also match. No strand conversion, "
            "assembly lifting or rsID-only matching occurs.",
            "Indels, structural variants, haplotypes, phase-dependent findings and polygenic "
            "scores are not interpreted. "
            "A missing match is not a negative screen or proof of health.",
            "Confirm medically relevant findings with a genetics professional and appropriate "
            "clinical testing before medical or reproductive decisions. "
            "Do not change medication based on this report.",
            "The report preserves its source snapshot. Reanalysis creates a separate version; "
            "later evidence can change classifications.",
            "Matching runs locally. Reference updates download public data only. "
            "Source links contact NCBI only when you choose to open them. "
            "No genetic data is sent to an AI service.",
        ],
    )
