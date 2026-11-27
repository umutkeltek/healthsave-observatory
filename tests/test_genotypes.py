import gzip

import pytest
from normalization.genotypes import parse_genotypes


def vcf(rows, *, build="GRCh38", samples="SAMPLE"):
    return (
        f"##fileformat=VCFv4.2\n##reference={build}\n"
        f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{samples}\n"
        + "\n".join(rows)
        + "\n"
    ).encode()


def parse(content, name="example.vcf", **kwargs):
    return parse_genotypes(
        content,
        name,
        assembly=kwargs.get("assembly", "GRCh38"),
        forward_strand=kwargs.get("forward_strand", True),
    )


def test_vcf_uses_actual_genotype_indices_and_accounts_for_every_row():
    result = parse(
        vcf(
            [
                "1\t10\trs1\tA\tG,T\t.\tPASS\tCLNSIG=fiction\tGT:DP:GQ\t1/2:20:35",
                "2\t20\trs2\tC\tT\t.\tPASS\t.\tGT\t./.",
                "3\t30\trs3\tG\tA\t.\tLowQual\t.\tGT\t0/1",
                "4\t40\trs4\tA\tAT\t.\tPASS\t.\tGT\t1/1",
                "1\t10\trs1\tA\tG,T\t.\tPASS\t.\tGT\t2|1",
            ]
        )
    )
    assert result.loci[0].alleles == ("G", "T")
    assert result.loci[0].reference == "A"
    assert result.loci[0].depth == 20
    assert result.loci[0].genotype_quality == 35
    assert result.counts == {
        "total_rows": 5,
        "accepted_loci": 1,
        "no_calls": 1,
        "filtered_rows": 1,
        "unsupported_rows": 1,
        "duplicate_rows": 1,
    }


@pytest.mark.parametrize(
    "content",
    [
        b"# 23andMe\n# reference build 37\n# rsid chromosome position genotype\nrs1\t1\t10\tAG\n",
        b"# AncestryDNA\n# reference build 37\n"
        b"rsid\tchromosome\tposition\tallele1\tallele2\nrs1\t1\t10\tA\tG\n",
    ],
)
def test_consumer_files_preserve_forward_alleles_and_build(content):
    result = parse(content, "example.txt", assembly="GRCh37")
    assert result.format == "genotype_table"
    assert result.assembly_in_file
    assert result.loci[0].alleles == ("A", "G")
    assert result.loci[0].reference is None
    assert result.loci[0].quality == "consumer_raw_unconfirmed"


def test_build_strand_and_multiple_people_are_not_guessed():
    content = vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1"])
    with pytest.raises(ValueError, match="assembly"):
        parse(content, assembly="GRCh37")
    with pytest.raises(ValueError, match="forward"):
        parse(content, forward_strand=False)
    with pytest.raises(ValueError, match="exactly one"):
        parse(vcf([], samples="ALICE\tBOB"))
    with pytest.raises(ValueError, match="reverse-strand"):
        parse(b"# strand=reverse\n" + content)


def test_corrupt_indices_and_conflicting_calls_fail_instead_of_guessing():
    with pytest.raises(ValueError, match="absent allele"):
        parse(vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/3"]))
    with pytest.raises(ValueError, match="conflicting calls"):
        parse(
            vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1", "1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t1/1"])
        )


def test_gzip_expansion_and_row_limits_are_enforced(monkeypatch):
    import normalization.genotypes as module

    content = vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1"])
    assert parse(gzip.compress(content), "example.vcf.gz").counts["accepted_loci"] == 1
    monkeypatch.setattr(module, "MAX_EXPANDED", 30)
    with pytest.raises(ValueError, match="expanded"):
        parse(gzip.compress(content), "example.vcf.gz")
    monkeypatch.setattr(module, "MAX_EXPANDED", 10000)
    monkeypatch.setattr(module, "MAX_LOCI", 0)
    with pytest.raises(ValueError, match="genotype rows"):
        parse(content)


def test_sample_filter_failure_excludes_calls_even_when_site_passes():
    from tests.test_genetic_evidence import GENOTYPES

    content = GENOTYPES.replace(b"GT\t0/1", b"GT:FT:DP:GQ\t0/1:LowGQ:1:0")
    parsed = parse_genotypes(content, "synthetic.vcf", assembly="GRCh38", forward_strand=True)
    assert parsed.counts["filtered_rows"] == 3
    assert parsed.counts["accepted_loci"] == 1
    assert parsed.loci[0].position == 11


@pytest.mark.parametrize("build", ["GRCh19", "hg37", "build19", "GRCh37 GRCh38"])
def test_invalid_or_conflicting_build_names_cannot_be_confirmed_away(build):
    with pytest.raises(ValueError, match="assembly"):
        parse(vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1"], build=build), assembly="GRCh37")


@pytest.mark.parametrize(
    "declaration", ["# strand=negative", "# negative strand", "# negative (-) strand"]
)
def test_negative_strand_metadata_is_rejected(declaration):
    with pytest.raises(ValueError, match="reverse-strand"):
        parse(declaration.encode() + b"\n" + vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1"]))


def test_concatenated_vcfs_and_reordered_columns_are_rejected():
    first = vcf(["1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1"])
    second = vcf(["1\t11\trs2\tC\tT\t.\tPASS\t.\tGT\t0/1"])
    with pytest.raises(ValueError, match="single format header"):
        parse(first + second)
    with pytest.raises(ValueError, match="standard column header"):
        parse(first.replace(b"REF\tALT", b"ALT\tREF"))
