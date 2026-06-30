import unittest

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.css import extract_css_file_observations
from repomap_kg.css_html_matching import extract_css_selector_match_observations
from repomap_kg.discovery import discover_observations
from repomap_kg.html import extract_html_file_observations
from repomap_kg.observations import RawObservation


HTML_FIXTURE = """\
<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="static/report.css">
    <link rel="stylesheet" href="https://example.com/remote.css">
  </head>
  <body>
    <header class="report-header">
      <span class="status-badge status-passed">Passed</span>
    </header>
    <main id="welcome" class="report-body">
      <a class="external" href="https://example.com/docs">Docs</a>
      <section class="tree-grid">
        <span class="path-cell">src/main.py</span>
        <span class="metric-cell">99%</span>
        <span class="status-cell">pass</span>
      </section>
      <div class="row">row</div>
      <h1 id="heading">Heading</h1>
      <div id="dup" class="status-badge">dup one</div>
      <div id="dup">dup two</div>
    </main>
  </body>
</html>
"""


CSS_FIXTURE = """\
.status-badge,
#welcome,
#heading,
a,
a.external,
.status-badge.status-passed,
.report-header .status-badge,
.a > .b,
.status-badge:hover,
#dup {
  color: #f8fafc;
}
"""


class CssHtmlMatchingUnitTests(unittest.TestCase):
    def test_matches_only_supported_selectors_for_linked_local_stylesheet(self):
        observations = (
            extract_html_file_observations("index.html", HTML_FIXTURE)
            + extract_css_file_observations("static/report.css", CSS_FIXTURE)
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertTrue(matches)
        self.assertTrue(all(item.kind == "css.selector_match" for item in matches))
        by_selector = {}
        for match in matches:
            by_selector.setdefault(match.metadata["selector_text"], set()).add(
                match.target
            )
            self.assertEqual(match.metadata["scope"], "local-html-css")
            self.assertTrue(match.metadata["not_runtime_style"])
            self.assertEqual(match.metadata["css_file"], "static/report.css")
            self.assertEqual(match.metadata["html_file"], "index.html")
            self.assertIn("selector_key", match.metadata)
            self.assertIn("html_key", match.metadata)
            self.assertIn("matched_components", match.metadata)

        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            by_selector[".status-badge"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain",
            by_selector["#welcome"],
        )
        self.assertIn(
            "html.anchor:file%3Aindex.html:heading",
            by_selector["#heading"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa",
            by_selector["a"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa",
            by_selector["a.external"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            by_selector[".status-badge.status-passed"],
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            by_selector[".report-header .status-badge"],
        )
        self.assertNotIn(".a > .b", by_selector)
        self.assertNotIn(".status-badge:hover", by_selector)
        self.assertNotIn("#dup", by_selector)

    def test_does_not_match_remote_or_unpaired_stylesheets(self):
        observations = (
            extract_html_file_observations("index.html", HTML_FIXTURE)
            + extract_css_file_observations(
                "unlinked.css",
                ".status-badge { color: red; }\n",
            )
            + extract_css_file_observations(
                "remote.css",
                ".status-badge { color: blue; }\n",
            )
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertEqual(matches, ())

    def test_ignores_malformed_or_unsupported_candidate_facts(self):
        observations = (
            RawObservation(
                kind="html.asset",
                source_id="index.html#remote-css",
                path="index.html",
                name="/html/head/link",
                target="external.url:https%3A%2F%2Fexample.com%2Fremote.css",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#non-css",
                path="index.html",
                name="/html/head/link[2]",
                target="file:README.md",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#bad-target",
                path="index.html",
                name="/html/head/link[3]",
                target="not a key",
                confidence="heuristic",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="static/report.css#missing-target",
                path="static/report.css",
                name="/rule:1/selector:1",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "selector_pointer": "/rule:1/selector:1",
                    "selector_text": ".status-badge",
                },
            ),
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertEqual(matches, ())

    def test_skips_descendant_without_matching_ancestor_and_deep_descendant(self):
        observations = (
            extract_html_file_observations(
                "index.html",
                """<html><head><link rel="stylesheet" href="static/report.css"></head>
<body><main><span class="status-badge">ok</span></main></body></html>""",
            )
            + extract_css_file_observations(
                "static/report.css",
                ".report-header .status-badge { color: green; }\n"
                ".one .two .status-badge { color: blue; }\n",
            )
        )

        matches = extract_css_selector_match_observations(observations)

        self.assertEqual(matches, ())

    def test_discovery_appends_selector_match_observations(self):
        with self.subTest("linked fixture"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                (root / "static").mkdir()
                (root / "index.html").write_text(HTML_FIXTURE)
                (root / "static" / "report.css").write_text(CSS_FIXTURE)
                (root / "static" / "unlinked.css").write_text(
                    ".status-badge { color: red; }\n"
                )

                observations = discover_observations(root)

        matches = [
            observation
            for observation in observations
            if observation.kind == "css.selector_match"
        ]

        self.assertTrue(matches)
        self.assertTrue(
            all(match.metadata["css_file"] == "static/report.css" for match in matches)
        )
        self.assertFalse(
            any(match.metadata["css_file"] == "static/unlinked.css" for match in matches)
        )

    def test_canonicalizes_selector_match_to_styles_edge(self):
        observations = (
            extract_html_file_observations("index.html", HTML_FIXTURE)
            + extract_css_file_observations("static/report.css", CSS_FIXTURE)
        )
        matches = extract_css_selector_match_observations(observations)

        result = canonicalize_observations(observations + matches)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        style_edges = [edge for edge in payload["edges"] if edge["kind"] == "styles"]
        self.assertTrue(style_edges)
        self.assertIn(
            (
                "css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1",
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan",
            ),
            {(edge["source_key"], edge["target_key"]) for edge in style_edges},
        )
        metadata = style_edges[0]["metadata"]
        self.assertIn("match_kinds", metadata)
        self.assertTrue(metadata["not_runtime_style_observed"])
        self.assertIn(
            "css.selector_match",
            {evidence["raw_kind"] for evidence in payload["evidence"]},
        )

    def test_selector_match_canonicalization_rejects_bad_keys(self):
        observations = [
            RawObservation(
                kind="css.selector_match",
                source_id="bad-source",
                path="static/report.css",
                name="tool:nix",
                target="html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain",
                confidence="heuristic",
                extractor="repo-css-html-matcher",
                extractor_version="0.1.0",
                metadata={
                    "selector_key": "tool:nix",
                    "html_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain",
                },
            ),
            RawObservation(
                kind="css.selector_match",
                source_id="bad-target",
                path="static/report.css",
                name="css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1",
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-css-html-matcher",
                extractor_version="0.1.0",
                metadata={
                    "selector_key": (
                        "css.selector:file%3Astatic%2Freport.css:"
                        "%2Frule%3A1%2Fselector%3A1"
                    ),
                    "html_key": "tool:nix",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertIn(
            "selector_key must be css.selector",
            payload["diagnostics"][0]["message"],
        )
        self.assertIn(
            "target must be html.element or html.anchor",
            payload["diagnostics"][1]["message"],
        )


if __name__ == "__main__":
    unittest.main()
