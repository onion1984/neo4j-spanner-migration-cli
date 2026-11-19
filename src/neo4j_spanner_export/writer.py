"""Sharded UTF-8 delimited file writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from .serializer import SerializerConfig, format_row


@dataclass
class WriteResult:
    """Summary of CSV shards written for a single table."""

    table_name: str
    row_count: int
    shard_paths: list[Path] = field(default_factory=list)


class ShardedDelimitedWriter:
    """Writes headerless UTF-8 (no BOM) delimited rows with automatic shard rotation."""

    def __init__(
        self,
        output_dir: Path,
        subdir: str,
        table_name: str,
        columns: list[str],
        serializer_cfg: SerializerConfig,
        chunk_rows: int = 500_000,
    ) -> None:
        if chunk_rows <= 0:
            raise ValueError(f"chunk_rows must be > 0, got {chunk_rows}")
        self.base_dir = output_dir / subdir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.table_name = table_name
        self.columns = columns
        self.serializer_cfg = serializer_cfg
        self.chunk_rows = chunk_rows

        self._shard_idx = 0
        self._rows_in_shard = 0
        self._total_rows = 0
        self._fh: TextIO | None = None
        self._shard_paths: list[Path] = []

    def _open_next_shard(self) -> None:
        if self._fh is not None:
            self._fh.close()
        shard_path = self.base_dir / f"{self.table_name}_part_{self._shard_idx:05d}.csv"
        self._shard_paths.append(shard_path)
        self._fh = shard_path.open("w", encoding="utf-8", newline="")
        self._shard_idx += 1
        self._rows_in_shard = 0

    def write_row(self, fields: list[str | None], pk: object = None) -> None:
        """Format and write one row, rotating to a new shard if chunk_rows is reached."""
        if self._fh is None or self._rows_in_shard >= self.chunk_rows:
            self._open_next_shard()
        assert self._fh is not None
        line = format_row(
            fields,
            self.serializer_cfg,
            table=self.table_name,
            columns=self.columns,
            pk=pk,
        )
        self._fh.write(line)
        self._rows_in_shard += 1
        self._total_rows += 1

    def close(self) -> WriteResult:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        return WriteResult(
            table_name=self.table_name,
            row_count=self._total_rows,
            shard_paths=list(self._shard_paths),
        )

    def __enter__(self) -> ShardedDelimitedWriter:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
