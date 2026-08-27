"""What the upload endpoint does with input that is trying to break it.

The engine binds to loopback and has no authentication, so the upload boundary
is the only boundary there is. Everything here arrived over HTTP from a
browser and none of it is trusted.

The rule these all check is one rule: **a bad file is a 4xx with a sentence,
never a 500.** A 500 is an unhandled exception, and an unhandled exception on
attacker-controlled input is the shape every other problem hides behind - it
means some code path met something it did not expect and nobody decided what
should happen. The message matters too, because the person who most often
sends a file this cannot read is a merchant with an unusual export rather than
an attacker.

Every case below was found by sending it. The three that came back 500 are
marked, because a test written after a fix is worth less than one that records
what the fix was for.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from milan.api.app import create_app
from milan.api.staging import LONGEST_NAME


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # `raise_server_exceptions=False` on purpose: an unhandled exception has to
    # arrive here as the 500 a browser would see, or these tests would pass by
    # crashing in a different place.
    return TestClient(create_app(tmp_path), raise_server_exceptions=False)


def send(client: TestClient, name: str, body: bytes) -> int:
    reply = client.post("/api/uploads", files=[("files", (name, body, "application/octet-stream"))])
    return int(reply.status_code)


def workbook_of(**parts: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in parts.items():
            archive.writestr(name.replace("__", "/").replace("_dot_", "."), body)
    return buffer.getvalue()


# ------------------------------------------------------------ getting out


TRAVERSALS = (
    "../../../../Windows/win.ini",
    "..%2f..%2f..%2fetc%2fpasswd",
    "....//....//etc/passwd",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "..\\..\\..\\Windows\\win.ini",
    "C:/Windows/win.ini",
    "/etc/passwd",
)


@pytest.mark.parametrize("probe", TRAVERSALS)
@pytest.mark.parametrize("route", ["/api/imports/", "/api/uploads/"])
def test_a_path_in_a_path_parameter_reads_nothing(
    client: TestClient, route: str, probe: str
) -> None:
    """Both of these take a name and turn it into a directory under the data
    root. `Path("root") / "../../etc/passwd"` is a real path, so the check is
    that nothing routes there rather than that nobody would try."""
    reply = client.get(route + probe)

    assert reply.status_code == 404, reply.text


@pytest.mark.parametrize(
    "name",
    [
        "../../../../evil.csv",
        "..\\..\\..\\evil.csv",
        "/tmp/evil.csv",
        "C:\\Windows\\evil.csv",
    ],
)
def test_a_filename_cannot_write_outside_the_staging_folder(tmp_path: Path, name: str) -> None:
    """A filename is attacker-controlled text that becomes a path. It is cut
    down to its last component on both separators, because a server may be
    handed either regardless of the platform it is running on."""
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)

    assert send(client, name, b"a,b\n1,2\n") == 200

    written = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert written, "the upload should have been staged somewhere"
    for path in written:
        assert path.name == "evil.csv"
        assert tmp_path in path.parents


# --------------------------------------------------------- names and sizes


def test_a_filename_longer_than_the_filesystem_takes_is_refused(
    client: TestClient,
) -> None:
    """Came back 500 before this.

    Nothing checked the length, so a four-hundred character name passed every
    guard, reached `write_bytes`, and returned `FileNotFoundError` from the
    standard library - which is what an OS says when a name is too long, and
    is indistinguishable at that point from a missing directory.
    """
    assert send(client, "a" * (LONGEST_NAME + 1) + ".csv", b"a,b\n1,2\n") == 422


def test_a_name_that_is_only_a_path_separator_is_refused(client: TestClient) -> None:
    assert send(client, "/", b"a,b\n1,2\n") == 422


def test_a_hidden_file_is_refused_rather_than_read(client: TestClient) -> None:
    """`.DS_Store` and `.gitignore` arrive in real folder uploads."""
    assert send(client, ".hidden.csv", b"a,b\n1,2\n") == 422


# ------------------------------------------------------------- workbooks


def test_something_that_is_not_a_zip_at_all(client: TestClient) -> None:
    assert send(client, "book.xlsx", b"this is not a zip file") == 422


def test_a_zip_that_is_not_a_workbook(client: TestClient) -> None:
    assert send(client, "book.xlsx", workbook_of(hello_dot_txt=b"nothing")) == 422


def test_a_workbook_declaring_an_external_entity(client: TestClient) -> None:
    """Came back 500 before this, and the crash was the only problem.

    Python's XML parser does not resolve external entities, so the file was
    never read - the parser refused the undefined entity and raised. What it
    raised was `ElementTree.ParseError`, which the workbook reader did not
    catch: a workbook is a zip full of XML, so malformed XML arrives as a
    parse error rather than as a bad zip.
    """
    hostile = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///C:/Windows/win.ini">]>'
        b"<workbook><sheets>&x;</sheets></workbook>"
    )
    body = workbook_of(**{"[Content_Types]_dot_xml": hostile, "xl__workbook_dot_xml": hostile})

    assert send(client, "xxe.xlsx", body) == 422


def test_a_gigabyte_compressed_into_a_megabyte(client: TestClient) -> None:
    """A zip bomb wearing a workbook's extension.

    Refused because it is not a workbook rather than because it is a bomb, and
    that is worth knowing rather than relying on: what protects the endpoint
    here is `openpyxl` needing a manifest before it reads anything, not a
    decompression limit. A well-formed workbook containing one enormous sheet
    would be a different question.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"\0" * (1024 * 1024 * 1024))

    assert send(client, "bomb.xlsx", buffer.getvalue()) == 422


# ------------------------------------------------------------------- text


def test_a_quote_that_is_never_closed(client: TestClient) -> None:
    """Came back 500 before this.

    `csv` caps one field at 128 KB, and an opening quote with no closing quote
    makes everything after it a single field. Raising the cap would move the
    failure from a library limit to however much memory the machine has, so
    the fix is to say what is wrong with the file.
    """
    assert send(client, "quote.csv", b'a,b\n"' + b"x" * (2 * 1024 * 1024)) == 422


def test_a_file_of_nul_bytes(client: TestClient) -> None:
    assert send(client, "nul.csv", b"a,b\n" + b"\x00" * 1000) == 422


def test_an_empty_file(client: TestClient) -> None:
    assert send(client, "empty.csv", b"") == 422


@pytest.mark.parametrize(
    "body",
    [
        "date,amount\n2026-07-01,100\n".encode("utf-16"),
        b"date,amount\n2026-07-01,\xff\xfe100\n",
        b"date,amount\r\n2026-07-01,100\r\n",
    ],
)
def test_an_encoding_this_did_not_expect_is_read_or_refused_but_never_crashes(
    client: TestClient, body: bytes
) -> None:
    """A merchant's export really can be UTF-16 - that is what Excel writes
    when somebody picks "Unicode Text" - so these are not all attacks. What
    they have in common is that the reader must reach a decision about them."""
    assert send(client, "odd.csv", body) in (200, 422)


def test_a_csv_with_fifty_thousand_columns(client: TestClient) -> None:
    """Wide rather than long, because every limit here counts bytes and rows.

    It is accepted, and that is the right answer: it is under the size cap and
    it parses. Nothing downstream will place it as a record kind, so it lands
    as a file the merchant is told nothing could be made of.
    """
    header = ",".join(f"c{index}" for index in range(50_000))
    row = ",".join("1" for _ in range(50_000))

    assert send(client, "wide.csv", f"{header}\n{row}\n".encode()) in (200, 422)


# ------------------------------------------------------------- the limits


def test_more_files_than_the_endpoint_takes(client: TestClient) -> None:
    files = [("files", (f"f{index}.csv", b"a,b\n1,2\n", "text/csv")) for index in range(40)]

    assert client.post("/api/uploads", files=files).status_code == 422


def test_two_files_with_the_same_name(client: TestClient) -> None:
    """They would land on top of each other, and the second would win silently."""
    files = [("files", ("same.csv", b"a,b\n1,2\n", "text/csv")) for _ in range(2)]

    assert client.post("/api/uploads", files=files).status_code == 422


def test_an_upload_with_no_files_at_all(client: TestClient) -> None:
    assert client.post("/api/uploads", files=[]).status_code == 422
