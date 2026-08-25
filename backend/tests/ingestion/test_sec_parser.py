from __future__ import annotations

from ingestion.sec_parser import ParsedDocument, parse_sec_filing, render_markdown


def test_parses_anchor_and_fallback_10k_sections_and_removes_noise() -> None:
    source = b"""
    <html><body>
      <div style="display:none"><ix:header>hidden XBRL metadata</ix:header></div>
      <table><tr><td><a href="#risk">Item 1A. Risk Factors</a></td></tr>
             <tr><td><a href="#mda">Item 7. MD&amp;A</a></td></tr></table>
      <div id="risk"></div>
      <div style="font-weight:700">Item 1A. Risk Factors</div>
      <div>Visible <ix:nonnumeric>risk disclosure</ix:nonnumeric>.</div>
      <div>-----</div>
      <div style="font-weight:700">Item 7. Management's Discussion and Analysis</div>
      <div id="mda">Results improved during the year.</div>
    </body></html>
    """

    document = parse_sec_filing(source, form="10-K", source_path="sample.htm")
    markdown = render_markdown(document)

    assert [section.key for section in document.sections] == ["item_1a", "item_7"]
    assert "Visible risk disclosure." in markdown
    assert "hidden XBRL metadata" not in markdown
    assert "-----" not in markdown
    assert "Table of Contents" not in markdown


def test_parses_prospectus_sections_lists_and_data_tables() -> None:
    source = b"""
    <html><body>
      <div style="font-weight:bold">Risk Factors</div>
      <table>
        <tr><td>&bull;</td><td>Our growth may not continue.</td></tr>
        <tr><td>&bull;</td><td>Competition may increase.</td></tr>
      </table>
      <div style="font-weight:bold">Business</div>
      <table>
        <tr><th>Year</th><th>Revenue</th></tr>
        <tr><td>2025</td><td>$100</td></tr>
      </table>
      <div style="font-weight:bold">Underwriting</div>
      <p>The underwriters may purchase additional shares.</p>
    </body></html>
    """

    document = parse_sec_filing(source, form="424B4", source_path="sample.htm")
    markdown = render_markdown(document)

    assert [section.key for section in document.sections] == [
        "risk_factors",
        "business",
        "underwriting",
    ]
    risk_blocks = document.sections[0].blocks
    assert [block.kind for block in risk_blocks] == ["list_item", "list_item"]
    table = document.sections[1].blocks[0]
    assert table.kind == "table"
    assert table.row_count == 2
    assert table.column_count == 2
    assert "| Year | Revenue |" in markdown


def test_markdown_offsets_and_serialization_are_deterministic() -> None:
    source = b"""
    <html><body>
      <div style="font-weight:bold">Risk Factors</div>
      <p>One meaningful paragraph.</p>
    </body></html>
    """
    first = parse_sec_filing(source, form="F-1", source_path="sample.htm")
    first_markdown = render_markdown(first)
    second = parse_sec_filing(source, form="F-1", source_path="sample.htm")
    second_markdown = render_markdown(second)

    block = first.sections[0].blocks[0]
    assert first_markdown[block.markdown_start : block.markdown_end] == block.text
    assert first_markdown == second_markdown
    assert first.to_dict() == second.to_dict()
    assert ParsedDocument.from_dict(first.to_dict()).to_dict() == first.to_dict()


def test_rejects_unsupported_form() -> None:
    try:
        parse_sec_filing(b"<html/>", form="20-F", source_path="sample.htm")
    except ValueError as error:
        assert "Unsupported SEC form" in str(error)
    else:
        raise AssertionError("Unsupported form was accepted")
