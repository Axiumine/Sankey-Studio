"""``TextDataSource`` over managed files: encodings, size cap, symlinks and descriptor hygiene."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, cast

import pytest

from sankey_studio.errors import SourceError, SourceNotFoundError, UnsafeSourceError
from sankey_studio.models import AppSettings, TextSource
from sankey_studio.sources import open_source
from sankey_studio.sources.base import Diagnostics
from sankey_studio.sources.files.paths import MIB
from tests.sources.text_support import of_file, open_fd_count, put

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from sankey_studio.models import RawLink
    from sankey_studio.sources.base import SourceContext

    Ctx = Callable[..., SourceContext]

CSV = "source,target,value,category\na,b,1,Food\nb,c,2,\n"
ROWS = [("a", "b", 1.0, "Food"), ("b", "c", 2.0, None)]


def test_a_csv_file(source_ctx: SourceContext) -> None:
    put(source_ctx, "flows.csv", CSV)
    out = of_file(source_ctx, "flows.csv")
    assert out.rows == ROWS
    assert out.warnings == []


class Named(NamedTuple):
    path: str
    content: str
    rows: list[tuple[str, str, float, str | None]]


NAMES = [
    Named("f.tsv", "source\ttarget\tvalue\na\tb\t1\n", [("a", "b", 1.0, None)]),
    Named("f.txt", "a [1] b | c\n", [("a", "b", 1.0, "c")]),
    Named("f.sankey", "a [1] b\n", [("a", "b", 1.0, None)]),
    Named("f.json", '[{"source":"a","target":"b","value":1}]', [("a", "b", 1.0, None)]),
    Named("f.ndjson", '{"source":"a","target":"b","value":1}\n', [("a", "b", 1.0, None)]),
    Named("UPPER.CSV", "source,target,value\na,b,1\n", [("a", "b", 1.0, None)]),
    Named("sub/dir/f.csv", "source,target,value\na,b,1\n", [("a", "b", 1.0, None)]),
]


@pytest.mark.parametrize("case", NAMES, ids=[c.path for c in NAMES])
def test_every_allowed_extension_and_nested_paths(source_ctx: SourceContext, case: Named) -> None:
    put(source_ctx, case.path, case.content)
    assert of_file(source_ctx, case.path).rows == case.rows


def test_crlf_and_utf8_bom(source_ctx: SourceContext) -> None:
    put(source_ctx, "w.csv", b"\xef\xbb\xbfsource,target,value\r\na,b,1\r\nc,d,2\r\n")
    assert of_file(source_ctx, "w.csv").rows == [("a", "b", 1.0, None), ("c", "d", 2.0, None)]


class Encoded(NamedTuple):
    encoding: str
    data: bytes


ENCODINGS = [
    Encoded("utf-8", "source,target,value\nz\u00fcrich,b,1\n".encode()),
    Encoded("cp1252", "source,target,value\nz\u00fcrich,b,1\n".encode("cp1252")),
    Encoded("latin-1", "source,target,value\nz\u00fcrich,b,1\n".encode("latin-1")),
    Encoded("utf-16", "source,target,value\nz\u00fcrich,b,1\n".encode("utf-16")),
    Encoded("utf-8-sig", b"\xef\xbb\xbf" + "source,target,value\nz\u00fcrich,b,1\n".encode()),
]


@pytest.mark.parametrize("case", ENCODINGS, ids=[c.encoding for c in ENCODINGS])
def test_the_declared_encoding_decodes_the_file(source_ctx: SourceContext, case: Encoded) -> None:
    put(source_ctx, "e.csv", case.data)
    out = of_file(source_ctx, "e.csv", encoding=case.encoding)
    assert out.rows == [("z\u00fcrich", "b", 1.0, None)]


def test_a_wrong_encoding_is_a_source_error_naming_the_line(source_ctx: SourceContext) -> None:
    put(source_ctx, "e.csv", "source,target,value\nz\u00fcrich,b,1\n".encode("cp1252"))
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "e.csv")  # utf-8 by default
    assert str(info.value) == "e.csv:2: cannot decode the data as utf-8"


def test_a_bad_byte_on_the_last_line_of_a_short_file_names_that_line(
    source_ctx: SourceContext,
) -> None:
    put(source_ctx, "bad.csv", b"source,target,value\na,b,1\n\xff,b,1\n")
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "bad.csv")
    assert str(info.value) == "bad.csv:3: cannot decode the data as utf-8"


def test_a_decode_error_far_into_the_file_names_the_real_line(source_ctx: SourceContext) -> None:
    good = "source,target,value\n" + "a,b,1\n" * 4000
    put(source_ctx, "late.csv", good.encode() + b"\xff,b,1\n")
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "late.csv")
    assert str(info.value) == "late.csv:4002: cannot decode the data as utf-8"


def test_a_sample_that_cannot_be_decoded_still_ends_in_the_line_error(
    source_ctx: SourceContext,
) -> None:
    put(source_ctx, "bad.tsv", b"source\ttarget\tvalue\n\xff\tb\t1\n")
    with pytest.raises(SourceError) as info:
        of_file(source_ctx, "bad.tsv", format="tsv")
    assert str(info.value) == "bad.tsv:2: cannot decode the data as utf-8"


def test_problems_are_labelled_with_the_path(source_ctx: SourceContext) -> None:
    put(source_ctx, "d/p.csv", "source,target,value\na,b,x\n")
    assert of_file(source_ctx, "d/p.csv").warnings == ["d/p.csv:2: value must be a positive number"]


def test_a_missing_file_is_not_found(source_ctx: SourceContext) -> None:
    with pytest.raises(SourceNotFoundError) as info:
        of_file(source_ctx, "nope.csv")
    assert str(info.value) == "nope.csv: no such file or directory"


EXTENSIONS_MESSAGE = (
    "only files with these extensions are allowed: .csv, .json, .ndjson, .sankey, .tsv, .txt"
)


def test_the_extension_allow_list_applies_to_loads(source_ctx: SourceContext) -> None:
    put(source_ctx, "notes.exe", "source,target,value\na,b,1\n")
    with pytest.raises(UnsafeSourceError) as info:
        of_file(source_ctx, "notes.exe")
    assert str(info.value) == EXTENSIONS_MESSAGE


def test_a_symlink_is_refused(source_ctx: SourceContext) -> None:
    secret = put(source_ctx, "../secret.csv", "source,target,value\nx,y,1\n")
    (source_ctx.sources_dir / "link.csv").symlink_to(secret)
    with pytest.raises(UnsafeSourceError, match=r"^link\.csv: symbolic links"):
        of_file(source_ctx, "link.csv")


def test_a_directory_is_refused(source_ctx: SourceContext) -> None:
    (source_ctx.sources_dir / "dir.csv").mkdir()
    with pytest.raises(UnsafeSourceError, match=r"^dir\.csv: not a regular file$"):
        of_file(source_ctx, "dir.csv")


class Size(NamedTuple):
    extra: int
    fits: bool


@pytest.mark.parametrize("case", [Size(0, True), Size(1, False)], ids=["limit", "limit+1"])
def test_the_upload_cap_applies_to_loads(make_source_ctx: Ctx, case: Size) -> None:
    ctx = make_source_ctx(settings=AppSettings(max_upload_mb=1))
    header = b"source,target,value\n"
    body = b"a,b,1\n"
    data = header + body + b"#" * (MIB - len(header) - len(body) + case.extra)
    assert len(data) == MIB + case.extra
    put(ctx, "big.csv", data)
    if case.fits:
        out = of_file(ctx, "big.csv", format="csv")
        assert out.rows[0] == ("a", "b", 1.0, None)
        return
    with pytest.raises(SourceError) as info:
        of_file(ctx, "big.csv", format="csv")
    assert str(info.value) == "big.csv: file is larger than 1 MB"


def test_a_file_that_grows_while_it_is_read_is_cut_off(make_source_ctx: Ctx) -> None:
    ctx = make_source_ctx(settings=AppSettings(max_upload_mb=1))
    path = put(ctx, "grow.csv", b"source,target,value\n" + b"a,b,1\n" * 100)
    spec = TextSource(origin="file", path="grow.csv", format="csv")
    rows = open_source(spec, ctx).iter_links(Diagnostics())
    assert next(rows) == ("a", "b", 1.0, None)
    with path.open("ab") as handle:
        handle.write(b"a,b,1\n" * (MIB // 6 + 10))
    with pytest.raises(SourceError, match=r"^grow\.csv: file is larger than 1 MB$"):
        list(rows)


def test_files_are_closed_after_a_complete_load(source_ctx: SourceContext) -> None:
    put(source_ctx, "c.csv", CSV)
    before = open_fd_count()
    for _ in range(5):
        assert of_file(source_ctx, "c.csv").rows == ROWS
    assert open_fd_count() == before


def test_files_are_closed_when_the_stream_is_abandoned(source_ctx: SourceContext) -> None:
    put(source_ctx, "c.csv", CSV)
    before = open_fd_count()
    rows = open_source(TextSource(origin="file", path="c.csv"), source_ctx).iter_links(
        Diagnostics()
    )
    assert next(rows) == ROWS[0]
    assert open_fd_count() == before + 1
    cast("Generator[RawLink]", rows).close()
    assert open_fd_count() == before


def test_files_are_closed_after_an_error(source_ctx: SourceContext) -> None:
    put(source_ctx, "bad.csv", b"source,target,value\n\xff,b,1\n")
    before = open_fd_count()
    with pytest.raises(SourceError):
        of_file(source_ctx, "bad.csv")
    assert open_fd_count() == before
