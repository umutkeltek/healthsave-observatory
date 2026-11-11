"""Local, atomically replaced ClinVar SNV indexes. Contains public data only."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import unquote

from contracts.genetics import GeneticReference
from normalization.genotypes import ASSEMBLIES, chromosome

MAX_REFERENCE_EXPANDED = 5 * 1024 * 1024 * 1024
MAX_REFERENCE_LINE = 4 * 1024 * 1024
MAX_REFERENCE_MATCHES = 100_000


class ReferenceUnavailable(ValueError):
    pass


class ReferenceMatchLimit(ValueError):
    pass


class ClinvarReferenceStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, assembly: str) -> Path:
        if assembly not in ASSEMBLIES:
            raise ValueError("Choose GRCh37 or GRCh38.")
        return self.root / f"{assembly}.sqlite"

    def metadata(self, assembly: str) -> dict | None:
        path = self.path(assembly)
        if not path.exists():
            return None
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                metadata = json.loads(conn.execute("SELECT value FROM metadata").fetchone()[0])
                GeneticReference.model_validate(metadata)
                if metadata["assembly"] != assembly:
                    raise ReferenceUnavailable("The local reference assembly is mismatched.")
                return metadata
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise ReferenceUnavailable(
                "The local reference index is unreadable. Install it again."
            ) from exc

    def install(
        self,
        source: Path,
        *,
        assembly: str,
        source_url: str,
        progress: Callable[[int], None] = lambda _count: None,
        deadline: float | None = None,
    ) -> dict:
        destination = self.path(assembly)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with source.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        fd, name = tempfile.mkstemp(prefix="reference-", suffix=".sqlite", dir=self.root)
        os.close(fd)
        staged = Path(name)
        count = skipped = total_bytes = 0
        reference = file_date = None
        batch = []
        try:
            with closing(sqlite3.connect(staged)) as conn:
                if deadline is not None:
                    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
                conn.execute("PRAGMA journal_mode=OFF")
                conn.execute("PRAGMA synchronous=OFF")
                conn.execute(
                    "CREATE TABLE variants (chrom TEXT, pos INTEGER, "
                    "id TEXT PRIMARY KEY, annotation TEXT NOT NULL)"
                )
                conn.execute("CREATE TABLE metadata (value TEXT NOT NULL)")
                with gzip.open(source, "rb") as handle:
                    while raw := handle.readline(MAX_REFERENCE_LINE + 1):
                        total_bytes += len(raw)
                        if len(raw) > MAX_REFERENCE_LINE or total_bytes > MAX_REFERENCE_EXPANDED:
                            raise ValueError(
                                "The public reference exceeds the supported size limit."
                            )
                        line = raw.decode("utf-8").rstrip("\r\n")
                        if line.startswith("##reference="):
                            reference = line.partition("=")[2]
                        if line.startswith("##fileDate="):
                            value = line.partition("=")[2]
                            file_date = date.fromisoformat(value).isoformat()
                        if not line or line.startswith("#"):
                            continue
                        if reference != assembly or file_date is None:
                            raise ValueError(
                                "ClinVar reference assembly or release date "
                                "is missing or mismatched."
                            )
                        cells = line.split("\t")
                        if len(cells) != 8:
                            raise ValueError("The ClinVar reference is not an eight-column VCF.")
                        chrom = chromosome(cells[0])
                        ref, alt, identifier = cells[3], cells[4], cells[2]
                        if (
                            chrom is None
                            or len(ref) != 1
                            or len(alt) != 1
                            or ref not in "ACGT"
                            or alt not in "ACGT"
                            or not identifier.isdigit()
                        ):
                            skipped += 1
                            continue
                        info = dict(
                            item.split("=", 1) for item in cells[7].split(";") if "=" in item
                        )
                        # Included haplotype-only and somatic-only records are not
                        # direct germline classifications of this single allele.
                        if not info.get("CLNSIG"):
                            skipped += 1
                            continue
                        pos = int(cells[1])
                        annotation = {
                            "chromosome": chrom,
                            "position": pos,
                            "reference": ref,
                            "alternate": alt,
                            "variation_id": identifier,
                        }
                        selected = {
                            "gene": ("GENEINFO", 2000),
                            "classification": ("CLNSIG", 1000),
                            "conditions": ("CLNDN", 2000),
                            "review_status": ("CLNREVSTAT", 1000),
                            "conflicts": ("CLNSIGCONF", 2000),
                            "hgvs": ("CLNHGVS", 1000),
                        }
                        annotation["details_truncated"] = any(
                            len(info.get(key, "")) > maximum for key, maximum in selected.values()
                        )
                        for target, (key, maximum) in selected.items():
                            annotation[target] = unquote(info.get(key, "")[:maximum])
                        batch.append((chrom, pos, identifier, json.dumps(annotation)))
                        count += 1
                        if len(batch) >= 5000:
                            conn.executemany("INSERT INTO variants VALUES (?, ?, ?, ?)", batch)
                            conn.commit()
                            batch.clear()
                            progress(count)
                if not count:
                    raise ValueError(
                        "No supported germline single-nucleotide annotations were found."
                    )
                conn.executemany("INSERT INTO variants VALUES (?, ?, ?, ?)", batch)
                conn.execute("CREATE INDEX variant_position ON variants(chrom, pos)")
                metadata = {
                    "assembly": assembly,
                    "release_date": file_date,
                    "sha256": digest,
                    "source_url": source_url,
                    "installed_at": datetime.now(UTC).isoformat(),
                    "record_count": count,
                    "excluded_reference_records": skipped,
                    "index_version": "clinvar-snv-1",
                }
                conn.execute("INSERT INTO metadata VALUES (?)", (json.dumps(metadata),))
                conn.commit()
                if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("The reference index failed its integrity check.")
            with staged.open("rb") as handle:
                os.fsync(handle.fileno())
            staged.replace(destination)
            return metadata
        finally:
            staged.unlink(missing_ok=True)

    def lookup(self, assembly: str, positions: list[tuple[str, int]]) -> tuple[dict, list[dict]]:
        """Read one consistent snapshot; no individual lookup ever leaves this host."""
        path = self.path(assembly)
        if not path.exists():
            raise ReferenceUnavailable(
                "Install the public ClinVar reference for this genome assembly first."
            )
        by_chromosome: dict[str, set[int]] = defaultdict(set)
        for chrom, pos in positions:
            by_chromosome[chrom].add(pos)
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                metadata = json.loads(conn.execute("SELECT value FROM metadata").fetchone()[0])
                GeneticReference.model_validate(metadata)
                if metadata["assembly"] != assembly:
                    raise ReferenceUnavailable("The local reference assembly is mismatched.")
                found = []
                for chrom, position_set in by_chromosome.items():
                    ordered = sorted(position_set)
                    for offset in range(0, len(ordered), 500):
                        chunk = ordered[offset : offset + 500]
                        placeholders = ",".join("?" for _ in chunk)
                        rows = conn.execute(
                            "SELECT annotation FROM variants WHERE chrom = ? "
                            f"AND pos IN ({placeholders}) ORDER BY pos, id",
                            [chrom, *chunk],
                        )
                        for row in rows:
                            if len(found) >= MAX_REFERENCE_MATCHES:
                                raise ReferenceMatchLimit(
                                    "This input matches too many reference records. "
                                    "Export a smaller set of loci and try again."
                                )
                            found.append(json.loads(row[0]))
                return metadata, found
        except ReferenceMatchLimit:
            raise
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise ReferenceUnavailable(
                "The local reference index could not be read. Install it again."
            ) from exc


def reference_store() -> ClinvarReferenceStore:
    root = Path(
        os.environ.get("GENETICS_REFERENCE_DIR", str(Path.home() / ".healthsave" / "genetics"))
    ).resolve()
    return ClinvarReferenceStore(root)
