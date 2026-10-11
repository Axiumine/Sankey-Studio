"""Text formats: sniffing and the parser table (one generator per format)."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from sankey_studio.sources.formats.csv_rows import csv_links
from sankey_studio.sources.formats.json_rows import json_links
from sankey_studio.sources.formats.sankeymatic import sankeymatic_links
from sankey_studio.sources.formats.sniff import ParsedFormat, detect_format, sniff_delimiter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from typing import TextIO

    from sankey_studio.models import RawLink
    from sankey_studio.sources.formats.job import ParseJob

    Parser = Callable[[ParseJob, TextIO], Iterator[RawLink]]

#: Format dispatch table. ``tsv`` shares the delimited-text parser (tab is its default delimiter).
PARSERS: Mapping[ParsedFormat, Parser] = MappingProxyType(
    {
        "csv": csv_links,
        "tsv": csv_links,
        "sankeymatic": sankeymatic_links,
        "json": json_links,
    }
)

__all__ = ["PARSERS", "ParsedFormat", "detect_format", "sniff_delimiter"]
