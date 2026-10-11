"""``util``: fail-closed URI masking and category identity helpers."""

from __future__ import annotations

import unicodedata

import pytest

from sankey_studio.util import (
    MASK,
    MASKED_URI,
    category_key,
    is_reserved_category,
    looks_masked,
    mask_uri,
    normalize_category,
)

# (input, substrings that must NEVER survive masking, expected output)
MASK_CASES: list[tuple[str, tuple[str, ...], str]] = [
    (
        "mongodb://bob:s3cret@db1:27017,db2:27017/app?replicaSet=rs&tlsCertificateKeyFilePassword=x",
        ("s3cret",),
        "mongodb://bob:***@db1:27017,db2:27017/app?replicaSet=rs&tlsCertificateKeyFilePassword=***",
    ),
    # SEC-3 bypasses reported by the security review (each leaked before the rewrite):
    (
        "mongodb://user@h/?authMechanism=MONGODB-AWS&authMechanismProperties=AWS_SESSION_TOKEN:abc123SESSION",
        ("abc123SESSION", "user"),
        "mongodb://***@h/?authMechanism=MONGODB-AWS&authMechanismProperties=***",
    ),
    ("mongodb://u:pa/ss@h1/db", ("pa/ss", "ss"), "mongodb://u:***@h1/db"),
    (
        "mongodb://admin:Pa#ss99@db.internal:27017/x",
        ("Pa", "ss99"),
        "mongodb://admin:***@db.internal:27017/x",
    ),
    ("mongodb://u:pa?ss@h1/db", ("pa?ss", "pa"), "mongodb://u:***@h1/db"),
    ("u:PW123@host", ("PW123",), MASK),
    ("PW123", ("PW123",), MASK),
    # token as username (no colon)
    ("mongodb://tok3n123@h/db", ("tok3n123",), "mongodb://***@h/db"),
    ("mongodb://u:p@ss@h/db", ("p@ss", "ss"), "mongodb://u:***@h/db"),
    # percent-encoded key spellings are not on the allow-list, so the value is masked
    (
        "mongodb://u:pw@h/?authMechanismPropert%69es=AWS_SESSION_TOKEN:zzz",
        ("zzz", "pw"),
        "mongodb://u:***@h/",
    ),
    (
        "mongodb://u:pw@h/db?password=hunter2&w=majority",
        ("hunter2",),
        "mongodb://u:***@h/db?password=***&w=majority",
    ),
    ("mongodb://u:pw@h/?appName=a b", ("a b",), "mongodb://u:***@h/?appName=***"),
    # plain, valid shapes survive in readable form
    (
        "mongodb+srv://u:pw@cluster0.abc.mongodb.net/db?retryWrites=true&w=majority",
        ("pw",),
        "mongodb+srv://u:***@cluster0.abc.mongodb.net/db?retryWrites=true&w=majority",
    ),
    ("MONGODB://U:pw@H/", ("pw",), "mongodb://U:***@H/"),
    (
        "mongodb://h1,h2:27018/?replicaSet=rs0&authSource=admin",
        (),
        "mongodb://h1,h2:27018/?replicaSet=rs0&authSource=admin",
    ),
    ("mongodb://u:pw@[::1]:27017/db", ("pw",), "mongodb://u:***@[::1]:27017/db"),
    ("mongodb://us%40er:p%40ss@h/db", ("p%40ss",), "mongodb://us%40er:***@h/db"),
    ("  mongodb://u:pw@h/db  ", ("pw",), "mongodb://u:***@h/db"),
    ("mongodb://h/?tls=true&ssl=false;w=1", (), "mongodb://h/?tls=true&ssl=false&w=1"),
    # doubt -> fully masked
    ("mongodb://", (), MASKED_URI),
    ("mongodb://u:pw@", ("pw",), MASKED_URI),
    ("mongodb://u:pw@/db", ("pw",), MASKED_URI),
    ("mongodb://u:pw", ("pw",), MASKED_URI),  # no '@': 'pw' is not a valid port, nothing is echoed
    ("mongodb://u:pw@h/db\nx", ("pw",), MASKED_URI),
    # a line break must not survive: "$" in a regex would tolerate a trailing one (use \Z)
    ("mongodb://u:pw@h\n/db", ("pw",), MASKED_URI),
    ("mongodb://u:pw@h:27017\n/db", ("pw",), MASKED_URI),
    ("mongodb://u:pw@h/db\n?w=1", ("pw",), MASKED_URI),
    ("mongodb://u:pw@h/db\r\n", ("pw",), "mongodb://u:***@h/db"),  # surrounding: stripped
    ("mongodb://u\n:pw@h/db", ("pw",), "mongodb://***@h/db"),
    ("mongodb://u:pw@h/db?w=1\n&appName=x", ("pw",), "mongodb://u:***@h/db?w=***&appName=x"),
    ("mongodb://u:pw@ünï.example/db", ("pw",), MASKED_URI),
    ("mongodb://u:pw@h/db#frag", ("pw",), MASKED_URI),
    # not a mongodb URI at all
    ("http://u:pw@h/", ("pw",), MASK),
    ("", (), MASK),
]


@pytest.mark.parametrize(("uri", "secrets", "expected"), MASK_CASES)
def test_mask_uri_fails_closed(uri: str, secrets: tuple[str, ...], expected: str) -> None:
    masked = mask_uri(uri)
    assert masked == expected
    for secret in secrets:
        assert secret not in masked
    assert mask_uri(masked) == masked  # idempotent


@pytest.mark.parametrize(
    "char", ["\n", "\r", "\t", "\x00", "\x0b", "\x1b", "\x7f", "\x85", "\u2028"]
)
@pytest.mark.parametrize(
    "template",
    [
        "mongodb://u{c}:pw123@h/db",
        "mongodb://u:pw123@h{c}/db",
        "mongodb://u:pw123@h:27017{c}/db",
        "mongodb://u:pw123@h/d{c}b",
        "mongodb://u:pw123@h/db{c}?w=1",
        "mongodb://u:pw123@h/db?w{c}=1",
        "mongodb://u:pw123@h/db?w=1{c}&appName=x",
        "mongodb://u:pw123@h1,h2{c}/db",
        "mongodb+srv://u:pw123@c{c}.example.com/db",
    ],
)
def test_mask_uri_output_never_holds_a_control_character(template: str, char: str) -> None:
    masked = mask_uri(template.format(c=char))
    assert "pw123" not in masked
    assert not [ch for ch in masked if unicodedata.category(ch) in {"Cc", "Cs", "Zl", "Zp"}]
    assert mask_uri(masked) == masked


def test_mask_uri_never_raises_on_garbage() -> None:
    junk = ("\x00", "mongodb://\x00@\x00", "mongodb://" + "a" * 100_000, "://", "mongodb+srv://@@@")
    assert [mask_uri(j) for j in junk] == [MASK, MASKED_URI, MASKED_URI, MASK, MASKED_URI]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("***", True),
        ("**********", True),
        ("  ****  ", True),
        ("mongodb://u:***@h/db", True),
        ("mongodb://***@h/db", True),
        ("mongodb://***", True),
        ("mongodb://h/db?authSource=***", True),
        ("mongodb://u:real@h/db", False),
        ("mongodb://u:a***b@h/db", False),
        # a real secret that merely ends in / contains "***" is not the placeholder
        ("mongodb://u:abc***@h/", False),
        ("mongodb://u:***abc@h/", False),
        ("mongodb://u:pa:***@h/", False),
        ("mongodb://u:x@***@h/", False),
        ("mongodb://u:p?k=***@h/db", False),
        ("mongodb://h/?appName=abc***", False),
        ("mongodb://h/?appName=***abc", False),
        ("mongodb+srv://u:abc***@h.example.com/?appName=x***", False),
        # the exact positions mask_uri writes
        ("MONGODB://U:***@H/db", True),
        ("mongodb+srv://u:***@h.example.com/db", True),
        ("mongodb+srv://***", True),
        ("mongodb://h/?appName=x&tlsFoo=***&w=1", True),
        ("mongodb://u:pw@h/?tlsFoo=***", True),
        ("", False),
        ("mongodb://h/db?appName=x", False),
    ],
)
def test_looks_masked(value: str, expected: bool) -> None:
    assert looks_masked(value) is expected


def test_masked_output_always_looks_masked_when_it_hid_something() -> None:
    for uri, secrets, _expected in MASK_CASES:
        if secrets:
            assert looks_masked(mask_uri(uri)), uri


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  Food  ", "Food"),
        ("Fast   Food\t\n", "Fast Food"),
        ("Cafe\u0301", "Caf\u00e9"),  # NFD -> NFC
        ("a\u00a0b", "a b"),  # no-break space collapses
    ],
)
def test_normalize_category(raw: str, normalized: str) -> None:
    assert normalize_category(raw) == normalized


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("a\x1fb", "a b"),  # whitespace controls collapse like any whitespace
        ("a\x85b", "a b"),
        ("a\x0b\x0cb", "a b"),
        ("\u0344", "\u0308\u0301"),  # NFC can LENGTHEN a name: callers must check the result
    ],
)
def test_normalize_category_collapses_whitespace_controls(raw: str, normalized: str) -> None:
    assert normalize_category(raw) == normalized


@pytest.mark.parametrize(
    "raw",
    ["\x00", "a\x00b", "\x01", "\x08x", "\x0e", "\x1b[31mred", "\x7f", "\x80", "\x9f", "\ud800"],
)
def test_normalize_category_rejects_control_characters_and_lone_surrogates(raw: str) -> None:
    for fn in (normalize_category, category_key, is_reserved_category):
        with pytest.raises(ValueError, match="control"):
            fn(raw)


def test_every_control_and_surrogate_code_point_is_covered() -> None:
    """The regex is an optimisation: prove it matches ``unicodedata`` for every Cc/Cs character."""
    for code in [*range(0x100), *range(0xD800, 0xE000)]:
        char = chr(code)
        if unicodedata.category(char) not in {"Cc", "Cs"}:
            continue
        if char.isspace():
            assert normalize_category(f"a{char}b") == "a b", hex(code)
        else:
            with pytest.raises(ValueError, match="control"):
                normalize_category(f"a{char}b")


def test_category_identity_ignores_case_spacing_and_unicode_form() -> None:
    assert category_key("Food") == category_key("food ") == category_key("FOOD")
    assert category_key("Cafe\u0301") == category_key("CAF\u00c9")
    assert category_key("Fast  Food") == category_key("fast food")
    assert category_key("Food") != category_key("Foods")


@pytest.mark.parametrize(
    "name", ["Uncategorized", "uncategorized", " UNCATEGORIZED ", "Other", "oTHER"]
)
def test_reserved_category_names(name: str) -> None:
    assert is_reserved_category(name)


@pytest.mark.parametrize("name", ["Others", "Un categorized", "Misc", "Other stuff", ""])
def test_non_reserved_category_names(name: str) -> None:
    assert not is_reserved_category(name)
