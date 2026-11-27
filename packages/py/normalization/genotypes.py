"""Bounded, offline parsing of single-person forward-strand genotype files.

No rsID-only matching, strand flipping, assembly lifting, or INFO interpretation.
Every input data row has exactly one accounted outcome.
"""

from __future__ import annotations

import gzip
import io
import re
import zlib
from dataclasses import dataclass, field

MAX_UPLOAD = 50 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
MAX_LOCI = 1_000_000
MAX_LINE = 65536
ASSEMBLIES = {"GRCh37", "GRCh38"}


@dataclass(frozen=True, slots=True)
class GenotypeLocus:
    chromosome: str
    position: int
    alleles: tuple[str, ...]
    reference: str | None
    source_id: str
    quality: str
    depth: int | None = None
    genotype_quality: float | None = None


@dataclass
class GenotypeFile:
    assembly: str
    format: str
    assembly_in_file: bool
    loci: list[GenotypeLocus]
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "total_rows": 0,
            "accepted_loci": 0,
            "no_calls": 0,
            "filtered_rows": 0,
            "unsupported_rows": 0,
            "duplicate_rows": 0,
        }
    )
    warnings: list[str] = field(default_factory=list)


def chromosome(raw: str) -> str | None:
    value = raw.removeprefix("chr").upper()
    value = {"23": "X", "24": "Y", "M": "MT"}.get(value, value)
    return value if value in {*(str(i) for i in range(1, 23)), "X", "Y", "MT"} else None


def _declared_builds(line: str) -> set[str]:
    builds = set()
    for match in re.finditer(r"\b(GRCh|build\s*|hg)(\d+)", line, re.IGNORECASE):
        family, version = match[1].strip().lower(), match[2]
        supported = {"19": "37", "38": "38"} if family == "hg" else {"37": "37", "38": "38"}
        if version not in supported:
            raise ValueError("The file declares an unsupported genome assembly.")
        builds.add("GRCh" + supported[version])
    return builds


def _vcf_locus(cells: list[str], line_number: int) -> tuple[GenotypeLocus | None, str]:
    if len(cells) != 10:
        raise ValueError(f"Line {line_number}: expected exactly one VCF sample.")
    chrom = chromosome(cells[0])
    try:
        position = int(cells[1])
    except ValueError as exc:
        raise ValueError(f"Line {line_number}: invalid position.") from exc
    if position <= 0 or position > 300_000_000:
        raise ValueError(f"Line {line_number}: position is outside supported coordinates.")
    keys, values = cells[8].split(":"), cells[9].split(":")
    if len(set(keys)) != len(keys) or len(values) > len(keys):
        raise ValueError(f"Line {line_number}: invalid VCF sample fields.")
    sample = dict(zip(keys, values, strict=False))
    genotype = sample.get("GT", ".")
    indices = re.split(r"[/|]", genotype)
    if any(value == "." for value in indices):
        return None, "no_calls"
    if len(indices) not in (1, 2):
        return None, "unsupported_rows"
    if not all(value.isdigit() for value in indices):
        raise ValueError(f"Line {line_number}: malformed genotype indices.")
    bases = [cells[3], *cells[4].split(",")]
    if any(int(index) >= len(bases) for index in indices):
        raise ValueError(f"Line {line_number}: genotype refers to an absent allele.")
    alleles = tuple(sorted(bases[int(index)].upper() for index in indices))
    if cells[6] not in ("PASS", ".") or sample.get("FT", ".") not in ("PASS", "."):
        return None, "filtered_rows"
    if (
        chrom is None
        or cells[3] not in "ACGT"
        or len(cells[3]) != 1
        or any(a not in "ACGT" or len(a) != 1 for a in alleles)
    ):
        return None, "unsupported_rows"
    depth = int(sample["DP"]) if re.fullmatch(r"\d{1,9}", sample.get("DP", "")) else None
    gq = (
        float(sample["GQ"])
        if re.fullmatch(r"\d{1,5}(?:\.\d{1,4})?", sample.get("GQ", ""))
        else None
    )
    return GenotypeLocus(
        chrom,
        position,
        alleles,
        cells[3],
        cells[2][:80],
        "file_filter_pass" if cells[6] == "PASS" else "quality_not_reported",
        depth,
        gq,
    ), "accepted_loci"


def _array_locus(cells: list[str], line_number: int) -> tuple[GenotypeLocus | None, str]:
    if len(cells) not in (4, 5):
        raise ValueError(f"Line {line_number}: expected four or five tab-separated columns.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", cells[0]):
        raise ValueError(f"Line {line_number}: invalid marker identifier.")
    chrom = chromosome(cells[1])
    try:
        position = int(cells[2])
    except ValueError as exc:
        raise ValueError(f"Line {line_number}: invalid position.") from exc
    if position <= 0 or position > 300_000_000:
        raise ValueError(f"Line {line_number}: position is outside supported coordinates.")
    genotype = "".join(cells[3:]).upper()
    if genotype in ("--", "00", "NN", "N", "-", "0", "..", "."):
        return None, "no_calls"
    if chrom is None or len(genotype) not in (1, 2) or any(a not in "ACGT" for a in genotype):
        return None, "unsupported_rows"
    return GenotypeLocus(
        chrom, position, tuple(sorted(genotype)), None, cells[0], "consumer_raw_unconfirmed"
    ), "accepted_loci"


def parse_genotypes(
    content: bytes, filename: str, *, assembly: str, forward_strand: bool
) -> GenotypeFile:
    if assembly not in ASSEMBLIES:
        raise ValueError(
            "Choose GRCh37 or GRCh38; genome assemblies are never guessed or converted."
        )
    if not forward_strand:
        raise ValueError("Confirm forward-reference-strand data before importing.")
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("Choose a non-empty genotype file no larger than 50 MB.")
    if not filename.lower().endswith((".txt", ".tsv", ".vcf", ".txt.gz", ".tsv.gz", ".vcf.gz")):
        raise ValueError("Choose TXT, TSV or a single-sample VCF, optionally gzip-compressed.")
    compressed = filename.lower().endswith(".gz")
    binary = gzip.GzipFile(fileobj=io.BytesIO(content)) if compressed else io.BytesIO(content)
    result = GenotypeFile(assembly, "", False, [])
    seen: dict[tuple[str, int], GenotypeLocus] = {}
    declared = set()
    header = False
    provider = False
    size = 0
    try:
        with binary:
            line_number = 0
            while raw := binary.readline(MAX_LINE + 1):
                line_number += 1
                size += len(raw)
                if len(raw) > MAX_LINE or size > MAX_EXPANDED:
                    raise ValueError(
                        "The expanded file or a line is too large. Export a smaller file."
                    )
                line = raw.decode("utf-8-sig" if line_number == 1 else "utf-8").strip()
                if not line:
                    continue
                if "\x00" in line:
                    raise ValueError("The file contains binary data.")
                if line.startswith("#"):
                    if re.search(
                        r"strand\s*[:=]\s*(?:reverse|minus|negative|-)|(?:reverse|minus|negative)\s+(?:\(-\)\s+)?strand",
                        line,
                        re.IGNORECASE,
                    ):
                        raise ValueError(
                            "The file declares reverse-strand data; "
                            "automatic strand conversion is not supported."
                        )
                    if line.startswith("##fileformat="):
                        if (
                            result.format
                            or result.counts["total_rows"]
                            or not re.fullmatch(r"##fileformat=VCFv4\.[0-9]+", line)
                        ):
                            raise ValueError("Use one complete VCF with a single format header.")
                        result.format = "vcf"
                    if any(name in line.lower() for name in ("23andme", "ancestrydna")):
                        provider = True
                    declared.update(_declared_builds(line))
                    if line.startswith("#CHROM"):
                        columns = line.split("\t")
                        if len(columns) != 10:
                            raise ValueError("Use a VCF with exactly one person/sample.")
                        if (
                            result.format != "vcf"
                            or header
                            or columns[:9]
                            != [
                                "#CHROM",
                                "POS",
                                "ID",
                                "REF",
                                "ALT",
                                "QUAL",
                                "FILTER",
                                "INFO",
                                "FORMAT",
                            ]
                        ):
                            raise ValueError(
                                "Use one VCF with the standard column header; "
                                "concatenated files are not supported."
                            )
                        header = True
                    continue
                cells = [cell.strip() for cell in line.split("\t")]
                if cells[:3] == ["rsid", "chromosome", "position"]:
                    if header or result.format == "vcf" or result.counts["total_rows"]:
                        raise ValueError(
                            "Use one genotype table; "
                            "concatenated or mixed file formats are not supported."
                        )
                    if cells[3:] not in (["genotype"], ["allele1", "allele2"]):
                        raise ValueError("Unsupported genotype table columns.")
                    result.format, header = "genotype_table", True
                    continue
                if not result.format and provider:
                    result.format, header = "genotype_table", True
                if not header or not result.format:
                    raise ValueError(
                        "Use a single-sample VCF or a 23andMe/Ancestry-style "
                        "tab-separated file with its header."
                    )
                result.counts["total_rows"] += 1
                if result.counts["total_rows"] > MAX_LOCI:
                    raise ValueError("Import at most 1,000,000 genotype rows at a time.")
                locus, outcome = (_vcf_locus if result.format == "vcf" else _array_locus)(
                    cells, line_number
                )
                if locus:
                    key = locus.chromosome, locus.position
                    if key in seen:
                        previous = seen[key]
                        if (
                            previous.alleles != locus.alleles
                            or previous.reference != locus.reference
                        ):
                            raise ValueError(
                                f"Line {line_number}: conflicting calls at the same position. "
                                "Resolve them in the source file."
                            )
                        outcome = "duplicate_rows"
                    else:
                        seen[key] = locus
                        result.loci.append(locus)
                result.counts[outcome] += 1
    except (UnicodeError, OSError, EOFError, zlib.error) as exc:
        raise ValueError("The file is not valid UTF-8 text or a complete gzip file.") from exc
    if declared and declared != {assembly}:
        raise ValueError("The selected genome assembly does not match the file header.")
    if not result.counts["total_rows"]:
        raise ValueError("The file has no genotype rows.")
    result.assembly_in_file = bool(declared)
    if not declared:
        result.warnings.append(
            "Assembly was supplied by the importer; the file header did not verify it."
        )
    result.warnings.extend(
        [
            "Only supported single-nucleotide calls on standard chromosomes are matched. "
            "Indels, structural variants and ambiguous calls are excluded.",
            "No-calls, excluded rows and missing matches are not negative health results.",
            "Genotypes are unconfirmed source data. "
            "Consumer raw files may contain false positives or false negatives.",
        ]
    )
    return result
