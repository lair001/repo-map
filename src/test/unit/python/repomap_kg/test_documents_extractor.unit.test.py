import json
import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch

from repomap_kg.documents import (
    extract_document_file_observations,
    extract_odf_file_observations,
)


def by_kind(observations):
    grouped = {}
    for observation in observations:
        grouped.setdefault(observation.kind, []).append(observation)
    return grouped


ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def odf_package(parts, *, compression=zipfile.ZIP_DEFLATED):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as package:
        for name, content in parts.items():
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            package.writestr(name, data)
    return buffer.getvalue()


def odt_content(*, secret_text="password docs2-secret-value"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Overview</text:h>
      <text:p>See <text:a xlink:href="https://example.com/docs">docs</text:a>.</text:p>
      <text:p>{secret_text}</text:p>
      <table:table table:name="Tasks">
        <table:table-row>
          <table:table-cell><text:p>Status</text:p></table:table-cell>
          <table:table-cell><text:p>Owner</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>open</text:p></table:table-cell>
          <table:table-cell><text:p>team</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
"""


def ods_content(*, secret_cell="docs2-cell-secret"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Budget">
        <table:table-row>
          <table:table-cell><text:p>item</text:p></table:table-cell>
          <table:table-cell><text:p>amount</text:p></table:table-cell>
          <table:table-cell><text:p>api_key</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>hosting</text:p></table:table-cell>
          <table:table-cell office:value-type="float" office:value="12.5"><text:p>12.5</text:p></table:table-cell>
          <table:table-cell><text:p>{secret_cell}</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>total</text:p></table:table-cell>
          <table:table-cell table:formula="of:=SUM([.B2:.B2])"><text:p>12.5</text:p></table:table-cell>
          <table:table-cell/>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


def manifest_xml():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest {ODF_NS}>
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="Pictures/local-image.png" manifest:media-type="image/png"/>
</manifest:manifest>
"""


def meta_xml(title="Fixture ODF"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta {ODF_NS}>
  <office:meta>
    <dc:title>{title}</dc:title>
    <meta:keyword>example</meta:keyword>
  </office:meta>
</office:document-meta>
"""


def styles_xml():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {ODF_NS}>
  <office:styles>
    <style:style style:name="Heading_20_1"/>
  </office:styles>
</office:document-styles>
"""


class DocumentsExtractorUnitTests(unittest.TestCase):
    def test_txt_extracts_document_sections_and_conservative_references(self):
        observations = extract_document_file_observations(
            "notes.txt",
            """# Overview
See docs/guide.txt and https://example.com/reference.

## Local Data
Open data/report.csv.

Token: docs/secret.txt should stay quiet.
""",
            repository_paths=frozenset(
                {"notes.txt", "docs/guide.txt", "data/report.csv"}
            ),
        )
        grouped = by_kind(observations)

        self.assertEqual(grouped["document.text_document"][0].target, "document.file:file%3Anotes.txt")
        self.assertEqual(len(grouped["document.text_section"]), 2)
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("file:docs/guide.txt", targets)
        self.assertIn("file:data/report.csv", targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Freference",
            targets,
        )
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs/secret.txt", serialized)

    def test_csv_extracts_table_columns_type_summaries_and_redacts_secret_columns(self):
        observations = extract_document_file_observations(
            "data.csv",
            """name,amount,password
alpha,42,docs1-secret-value
beta,7,another-secret-value
""",
        )
        grouped = by_kind(observations)

        table = grouped["document.table_document"][0]
        self.assertEqual(table.metadata["format"], "csv")
        self.assertEqual(table.metadata["row_count"], 2)
        self.assertEqual(table.metadata["column_count"], 3)
        columns = {observation.metadata["column_name_summary"]: observation for observation in grouped["document.table_column"]}
        self.assertEqual(columns["amount"].metadata["type_summary"], "integer")
        redacted = next(
            observation
            for observation in grouped["document.table_column"]
            if observation.metadata["redacted"]
        )
        self.assertEqual(redacted.metadata["column_name_summary"], "[redacted]")
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs1-secret-value", serialized)
        self.assertNotIn("another-secret-value", serialized)

    def test_tsv_extracts_table_with_tab_delimiter(self):
        observations = extract_document_file_observations(
            "data.tsv",
            "name\tactive\nalpha\ttrue\nbeta\tfalse\n",
        )
        grouped = by_kind(observations)

        self.assertEqual(grouped["document.table_document"][0].metadata["format"], "tsv")
        self.assertEqual(grouped["document.table_document"][0].metadata["delimiter"], "\\t")
        active = next(
            observation
            for observation in grouped["document.table_column"]
            if observation.metadata["column_name_summary"] == "active"
        )
        self.assertEqual(active.metadata["type_summary"], "boolean")

    def test_csv_without_header_uses_structural_column_names(self):
        observations = extract_document_file_observations(
            "numbers.csv",
            "1,2.5\n3,4.5\n",
        )
        grouped = by_kind(observations)

        self.assertFalse(grouped["document.table_document"][0].metadata["header_present"])
        columns = grouped["document.table_column"]
        self.assertEqual(columns[0].metadata["column_name_summary"], "column-1")
        self.assertEqual(columns[0].metadata["type_summary"], "integer")
        self.assertEqual(columns[1].metadata["type_summary"], "decimal")

    def test_empty_csv_emits_empty_table_document(self):
        observations = extract_document_file_observations("empty.csv", "\n")

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].kind, "document.table_document")
        self.assertEqual(observations[0].metadata["row_count"], 0)
        self.assertEqual(observations[0].metadata["column_count"], 0)

    def test_ragged_csv_emits_parse_error_without_table_structure(self):
        observations = extract_document_file_observations(
            "bad.csv",
            "name,amount\nalpha,1\nbeta,2,extra\n",
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].kind, "document.parse_error")
        self.assertEqual(observations[0].metadata["error_kind"], "ragged-row")

    def test_txt_reference_placeholders_for_absolute_repo_escape_and_dynamic_paths(self):
        observations = extract_document_file_observations(
            "docs/notes.txt",
            """# Paths
Read /Users/example/private.txt
Read ../../outside.txt
Read ${DOCS_ROOT}/dynamic.txt
""",
        )
        targets = {
            observation.target
            for observation in observations
            if observation.kind == "document.reference"
        }

        self.assertIn("external:file:absolute-document-reference", targets)
        self.assertIn("unknown:file:repo-escaping-document-reference", targets)
        self.assertIn("dynamic:file:dynamic-document-reference", targets)

    def test_latex_extracts_sections_commands_and_static_references_without_compiling(self):
        with patch("subprocess.run") as run:
            observations = extract_document_file_observations(
                "paper.tex",
                r"""\section{Intro}
\label{sec:intro}
\input{chapter}
\includegraphics{figures/diagram.png}
\bibliography{references}
\url{https://example.com/paper}
""",
                repository_paths=frozenset(
                    {
                        "paper.tex",
                        "chapter.tex",
                        "figures/diagram.png",
                        "references.bib",
                    }
                ),
            )

        run.assert_not_called()
        grouped = by_kind(observations)
        self.assertEqual(grouped["document.latex_document"][0].metadata["compiled"], False)
        self.assertEqual(grouped["document.latex_section"][0].metadata["command"], "section")
        commands = {observation.metadata["command"] for observation in grouped["document.latex_command"]}
        self.assertIn("input", commands)
        self.assertIn("includegraphics", commands)
        self.assertIn("bibliography", commands)
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("file:chapter.tex", targets)
        self.assertIn("file:figures/diagram.png", targets)
        self.assertIn("file:references.bib", targets)
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fpaper", targets)

    def test_latex_strips_comments_and_extracts_href_url(self):
        observations = extract_document_file_observations(
            "paper.tex",
            r"""\section{Intro} % \input{ignored}
\href{https://example.com/href}
""",
        )
        grouped = by_kind(observations)

        commands = {observation.metadata["command"] for observation in grouped["document.latex_command"]}
        self.assertNotIn("input", commands)
        self.assertIn("href", commands)
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fhref", targets)

    def test_unsupported_native_formats_are_not_docs1_observations(self):
        self.assertEqual(extract_document_file_observations("ignored.pdf", "%PDF"), ())
        self.assertEqual(
            extract_document_file_observations("ignored.docx", "zip-bytes"),
            (),
        )

    def test_observations_json_does_not_include_secret_table_values(self):
        observations = extract_document_file_observations(
            "secrets.csv",
            "account_number,amount\nacct-very-secret,5\n",
        )

        payload = json.loads("[" + ",".join(item.to_json_line() for item in observations) + "]")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("acct-very-secret", serialized)

    def test_odt_extracts_headings_tables_and_references_without_body_leakage(self):
        with patch("subprocess.run") as run:
            observations = extract_odf_file_observations(
                "notes.odt",
                odf_package(
                    {
                        "content.xml": odt_content(),
                        "meta.xml": meta_xml(),
                        "styles.xml": styles_xml(),
                        "META-INF/manifest.xml": manifest_xml(),
                    }
                ),
            )

        run.assert_not_called()
        grouped = by_kind(observations)
        document = grouped["document.odf_document"][0]
        self.assertEqual(document.metadata["format"], "odt")
        self.assertFalse(document.metadata["template"])
        self.assertEqual(document.metadata["paragraph_count"], 2)
        self.assertEqual(document.metadata["heading_count"], 1)
        self.assertEqual(document.metadata["table_count"], 1)
        self.assertEqual(grouped["document.odf_text"][0].metadata["heading_summary"], "Overview")
        self.assertEqual(grouped["document.odf_table"][0].metadata["display_name"], "Tasks")
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fdocs", targets)
        self.assertIn("unknown:document.reference:odf-internal-package-part", targets)
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs2-secret-value", serialized)

    def test_ods_extracts_sheets_columns_and_does_not_evaluate_formulas(self):
        observations = extract_odf_file_observations(
            "spreadsheet.ods",
            odf_package(
                {
                    "content.xml": ods_content(),
                    "meta.xml": meta_xml("Budget"),
                    "META-INF/manifest.xml": manifest_xml(),
                }
            ),
        )
        grouped = by_kind(observations)

        document = grouped["document.odf_document"][0]
        self.assertEqual(document.metadata["format"], "ods")
        self.assertFalse(document.metadata["template"])
        self.assertEqual(document.metadata["sheet_count"], 1)
        self.assertEqual(document.metadata["formula_count"], 1)
        self.assertFalse(document.metadata["formulas_evaluated"])
        sheet = grouped["document.odf_sheet"][0]
        self.assertEqual(sheet.metadata["display_name"], "Budget")
        self.assertEqual(sheet.metadata["row_count"], 2)
        self.assertEqual(sheet.metadata["column_count"], 3)
        columns = grouped["document.odf_column"]
        self.assertEqual(columns[0].metadata["column_name_summary"], "item")
        self.assertEqual(columns[1].metadata["type_summary"], "decimal")
        redacted = next(column for column in columns if column.metadata["redacted"])
        self.assertEqual(redacted.metadata["column_name_summary"], "[redacted]")
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs2-cell-secret", serialized)

    def test_ott_and_ots_are_template_variants(self):
        ott = by_kind(
            extract_odf_file_observations(
                "template.ott",
                odf_package({"content.xml": odt_content(), "META-INF/manifest.xml": manifest_xml()}),
            )
        )["document.odf_document"][0]
        ots = by_kind(
            extract_odf_file_observations(
                "sheet-template.ots",
                odf_package({"content.xml": ods_content(), "META-INF/manifest.xml": manifest_xml()}),
            )
        )["document.odf_document"][0]

        self.assertEqual(ott.metadata["format"], "ott")
        self.assertTrue(ott.metadata["template"])
        self.assertEqual(ots.metadata["format"], "ots")
        self.assertTrue(ots.metadata["template"])

    def test_odf_package_safety_rejects_traversal_dangerous_xml_and_limits(self):
        traversal = extract_odf_file_observations(
            "bad.odt",
            odf_package({"../content.xml": odt_content()}),
        )
        doctype = extract_odf_file_observations(
            "dangerous.odt",
            odf_package({"content.xml": "<!DOCTYPE x [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><x/>"}),
        )
        limited = extract_odf_file_observations(
            "large.odt",
            odf_package({"content.xml": odt_content()}),
            max_total_uncompressed_bytes=10,
        )
        malformed = extract_odf_file_observations("broken.odt", b"not-a-zip")

        self.assertEqual(traversal[0].metadata["error_kind"], "zip-path-traversal")
        self.assertEqual(doctype[0].metadata["error_kind"], "dangerous-xml")
        self.assertEqual(limited[0].metadata["error_kind"], "zip-uncompressed-limit")
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-zip")

    def test_odf_unsupported_native_formats_are_not_docs2_observations(self):
        package = odf_package({"content.xml": odt_content()})

        self.assertEqual(extract_odf_file_observations("ignored.docx", package), ())
        self.assertEqual(extract_odf_file_observations("ignored.xlsx", package), ())


if __name__ == "__main__":
    unittest.main()
