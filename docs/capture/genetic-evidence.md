# Private genetic evidence

Open **Explore → Genetics** in HealthSave Observatory to match a genotype file
against public ClinVar variant annotations. Your file is processed on your own
Observatory. Matching does not send genotypes to NCBI, Promethease, or an AI service.

This is a source-linked evidence report, not a diagnosis or personal risk score.
It is an independent implementation of variant evidence retrieval. It does not
embed Promethease, copy SNPedia, or require a Promethease account.

## Import and read a report

1. Install the public reference for **GRCh37** or **GRCh38**. Confirm the download
   in the Genetics page. Each assembly downloads hundreds of MB from NCBI and
   needs additional disk space for the local index. Installation runs in the
   background; its progress and failures remain visible.
2. Choose a single-person 23andMe/Ancestry-style TXT/TSV or a single-sample VCF.
   Gzip is supported; extract ZIP archives first. Limits: 50 MB uploaded,
   100 MB expanded, 1,000,000 data rows. Choose the file's documented genome build
   and confirm that its alleles use the forward reference strand.
3. Confirm permission to process the primary person's file and acknowledge the
   interpretation limits. **Original retention is off by default.** Reports are
   retained privately; the original is stored only when selected.
4. Read coverage and exclusions before individual matches. Search by gene,
   condition, coordinate, HGVS or ClinVar identifier; filter by classification
   and source review. Each result links to its public ClinVar record.
5. Download the complete saved report as JSON. Printing includes the **currently
   visible page and filters**, with displayed counts; it is an excerpt, not a
   complete export. Original-file download is available only when retained.

ClinVar links are ordinary external links: opening one contacts NCBI with that
public variant identifier. Automatic matching itself remains local.

## What matching means

- Genome assembly, chromosome, position and alternate allele must match exactly.
  VCF reference alleles must match too. Consumer tables do not contain a reference
  allele, so matching depends on the confirmed forward strand and genome build.
- No rsID-only matching, genome lifting, strand guessing or automatic conversion.
- Only supported single-nucleotide germline records with a direct ClinVar
  classification are indexed. Indels, structural variants, haplotype-only and
  somatic-only classifications are excluded. Chromosome codes 23/24 map to X/Y;
  ambiguous provider codes 25/26 are excluded.
- No-calls, source-filter failures (site FILTER or sample FT), unsupported rows
  and duplicates have separate counts. Contradictory calls at a position reject
  the file. Up to 15,000 matched annotations are saved; additional matches are
  counted explicitly. More than 100,000 reference candidates requires a smaller
  input rather than silently truncating the lookup.
- ClinVar review stars describe **review of the public classification**. They
  do not validate a consumer genotype or estimate personal risk. The report
  preserves uncertain and conflicting classifications and source quality fields.
- A missing match does not rule out a genetic condition. A pathogenic variant
  annotation alone does not establish disease: inheritance, phase, penetrance,
  family history and clinical context matter and are not inferred here.
- These reports do not recommend medication changes, calculate polygenic scores,
  infer ancestry, or combine blood and DNA results into disease probabilities.
  Medically relevant results need professional interpretation and, where
  appropriate, confirmation with a clinical test.

## Versions, retention and deletion

Every report stores the input SHA-256, source release and download SHA-256, index
and analysis versions, exclusions, and the actual annotations used. Updating a
reference never rewrites saved reports. With a retained original, reanalysis
creates a report for the new reference/engine; repeating the same analysis
returns the existing version. Earlier reports remain available in the selector.

You can remove the original alone, preserving reports, or delete the document
and all its report versions. Both actions require confirmation. Backups and
previously downloaded copies are separate and are not erased by these actions.
The feature is admin-only and belongs to the primary person. Participant read
and ingestion keys cannot access DNA records or manage references.

## Installation and operation

The default Compose configuration stores public indexes in the
`genetics_reference` volume mounted at `/app/genetics`. Normal restarts and
application updates preserve this volume. Outside Compose, set
`GENETICS_REFERENCE_DIR` to a writable directory; the default is
`~/.healthsave/genetics`. This directory contains public reference data only.
Private originals and reports are stored in PostgreSQL, covered by the owner's
usual database security and backup controls. This feature does not add
application-level encryption of PostgreSQL records.

The installer downloads only the fixed NCBI assembly URL using HTTPS, without
redirects or personal-data parameters. One install runs per reference directory.
A staged index replaces the previous one only after parsing and integrity
checks pass. A failed or interrupted install leaves the prior complete index
usable; retry from the page. Allow at least 3 GB of free space per assembly,
including temporary files, and more for retained private files and backups.
Old references show a warning after 90 days; updates are always explicit.

Reverse proxies must allow a 50 MB request and at least a 120-second upstream
request for imports. The bundled Next.js proxy allows these uploads. Configure
any additional ingress proxy accordingly.

## Scientific sources

- [ClinVar data use and limits](https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/)
- [ClinVar review status](https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/)
- [ClinVar bulk downloads](https://www.ncbi.nlm.nih.gov/clinvar/docs/downloads/)
- [23andMe genome build and strand](https://customercare.23andme.com/hc/en-us/articles/212883767-Which-Reference-Genome-and-Strand-Does-23andMe-Use)
- [Ancestry raw DNA download](https://help.ancestry.com/hc/en-us/articles/53933317283603-Downloading-DNA-Data)

Public reference compatibility and indexing are tested separately from matching
correctness. Synthetic fixtures verify matching behavior; these tests do not
establish clinical validity or the accuracy of a person's source genotype.
