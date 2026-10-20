"""Acquire source files: find or download them, verify checksums, record provenance.

Every original file lives in the raw data directory (``data/raw`` by default, not versioned). Next to it
the pipeline keeps ``<file>.provenance.json``: where the file came from, when it was retrieved, its size
and SHA-256. A file placed there by hand (an agency delivery, a browser download) gets a provenance
record the first time the pipeline sees it, with the file's modification time as the retrieval time and
that basis stated.

Downloads use https only, stream to a temporary file and are renamed into place when complete; an
expected checksum in the profile is enforced. Credentials come from environment variables named in the
profile, never from the profile itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.pipeline.errors import SourceError
from app.pipeline.profile import SourceConfig, raw_path

logger = logging.getLogger(__name__)

CHUNK: Final = 1024 * 1024
DOWNLOAD_TIMEOUT_S: Final = 600


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    code: str
    path: Path
    sha256: str
    size_bytes: int
    reference: str
    version: str
    retrieved_at: datetime | None
    retrieved_basis: str


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _provenance_path(path: Path) -> Path:
    return path.with_name(path.name + ".provenance.json")


def _download(url: str, target: Path, header: str | None) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise SourceError(f"refusing to download {url}: only https is allowed")
    request = urllib.request.Request(url, headers={"User-Agent": "gis-core-service reference data pipeline"})  # noqa: S310 - https only, checked above
    if header:
        request.add_header("Authorization", header)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    logger.info("downloading source file", extra={"url": url, "target": str(target)})
    try:
        with (
            urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response,  # noqa: S310 - https only
            partial.open("wb") as out,
        ):
            while block := response.read(CHUNK):
                out.write(block)
            headers = {
                "lastModified": response.headers.get("Last-Modified"),
                "etag": response.headers.get("ETag"),
            }
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise SourceError(f"download of {url} failed: {exc}", extensions={"url": url}) from exc
    partial.replace(target)
    return {key: value for key, value in headers.items() if value}


def acquire(
    source: SourceConfig, raw_dir: Path, *, profile_dir: Path | None = None, allow_download: bool = True
) -> AcquiredSource:
    path = raw_path(raw_dir, source, profile_dir)
    provenance_path = _provenance_path(path)
    url = source.download or (os.environ.get(source.download_env) if source.download_env else None)
    if not path.exists():
        if url is None:
            raise SourceError(
                f"source {source.code}: {path} is missing and no download is configured; place the file "
                "there",
                extensions={"source": source.code, "path": str(path)},
            )
        if not allow_download:
            raise SourceError(
                f"source {source.code}: {path} is missing; download it from {url} or allow downloads",
                extensions={"source": source.code, "path": str(path), "url": url},
            )
        header = os.environ.get(source.auth_header_env) if source.auth_header_env else None
        response = _download(url, path, header)
        record: dict[str, Any] = {
            "source": source.code,
            "url": url,
            "retrievedAt": datetime.now(UTC).isoformat(),
            "retrievedBasis": "downloaded by the pipeline",
            **response,
        }
    elif provenance_path.exists():
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
    else:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        record = {
            "source": source.code,
            "url": url,
            "retrievedAt": modified.isoformat(),
            "retrievedBasis": "file modification time ("
            + (
                "the file is kept next to the profile"
                if source.base == "profile"
                else "the file was placed in the raw directory by hand"
            )
            + ")",
        }
    checksum = sha256_of(path)
    if source.sha256 is not None and checksum != source.sha256:
        raise SourceError(
            f"source {source.code}: {path.name} has SHA-256 {checksum}, the profile expects {source.sha256}",
            extensions={"source": source.code, "expected": source.sha256, "actual": checksum},
        )
    if record.get("sha256") not in (None, checksum):
        raise SourceError(
            f"source {source.code}: {path.name} changed since it was retrieved (provenance records "
            f"{record['sha256']}); remove {provenance_path.name} if the new file is intended",
            extensions={"source": source.code},
        )
    record.update(sha256=checksum, sizeBytes=path.stat().st_size, file=path.name)
    provenance_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    version = source.version or _version(source, path)
    retrieved = record.get("retrievedAt")
    return AcquiredSource(
        code=source.code,
        path=path,
        sha256=checksum,
        size_bytes=int(record["sizeBytes"]),
        reference=str(record.get("url") or url or source.url or path.name),
        version=version,
        retrieved_at=datetime.fromisoformat(retrieved) if isinstance(retrieved, str) else None,
        retrieved_basis=str(record.get("retrievedBasis", "")),
    )


def _version(source: SourceConfig, path: Path) -> str:
    if source.version_from == "osm_replication_timestamp":
        header = read_osm_pbf_header(path)
        timestamp = header.get("osmosis_replication_timestamp")
        if timestamp is None:
            raise SourceError(
                f"source {source.code}: {path.name} has no replication timestamp; state version in the "
                "profile"
            )
        moment = datetime.fromtimestamp(int(timestamp), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        sequence = header.get("osmosis_replication_sequence_number")
        return f"OpenStreetMap data as of {moment}" + (
            f" (replication sequence {sequence})" if sequence else ""
        )
    raise SourceError(f"source {source.code}: no version stated")


# --- OpenStreetMap PBF header ---------------------------------------------------------------------------


def _varint(data: bytes, position: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if position >= len(data):
            raise SourceError("truncated varint in OSM PBF header")
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7
        if shift > 63:
            raise SourceError("invalid varint in OSM PBF header")


def _fields(data: bytes) -> list[tuple[int, int | bytes]]:
    """Protocol buffer fields (number, value) of a message: varints and length-delimited values only."""
    fields: list[tuple[int, int | bytes]] = []
    position = 0
    while position < len(data):
        key, position = _varint(data, position)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, position = _varint(data, position)
            fields.append((number, value))
        elif wire == 2:
            length, position = _varint(data, position)
            fields.append((number, data[position : position + length]))
            position += length
        elif wire == 1:
            position += 8
        elif wire == 5:
            position += 4
        else:
            raise SourceError(f"unsupported wire type {wire} in OSM PBF header")
    return fields


def read_osm_pbf_header(path: Path) -> dict[str, Any]:
    """The HeaderBlock of an OSM PBF file: writing program, source, replication timestamp and sequence."""
    with path.open("rb") as stream:
        (header_size,) = struct.unpack(">I", stream.read(4))
        if not 0 < header_size < 64 * 1024:
            raise SourceError(f"{path.name} is not an OSM PBF file")
        blob_header = dict(_fields(stream.read(header_size)))
        if blob_header.get(1) != b"OSMHeader":
            raise SourceError(f"{path.name} does not start with an OSMHeader block")
        size = blob_header.get(3)
        if not isinstance(size, int) or size > 32 * 1024 * 1024:
            raise SourceError(f"{path.name}: implausible OSMHeader size")
        blob = dict(_fields(stream.read(size)))
    raw = blob.get(1)
    compressed = blob.get(3)
    if isinstance(raw, bytes):
        header = raw
    elif isinstance(compressed, bytes):
        header = zlib.decompress(compressed)
    else:
        raise SourceError(f"{path.name}: unsupported OSMHeader compression")
    names = {
        16: "writingprogram",
        17: "source",
        32: "osmosis_replication_timestamp",
        33: "osmosis_replication_sequence_number",
        34: "osmosis_replication_base_url",
    }
    result: dict[str, Any] = {}
    for number, value in _fields(header):
        if number in names:
            result[names[number]] = value.decode("utf-8") if isinstance(value, bytes) else value
        elif number in (4, 5):
            key = "required_features" if number == 4 else "optional_features"
            result.setdefault(key, []).append(value.decode("utf-8") if isinstance(value, bytes) else value)
    return result
