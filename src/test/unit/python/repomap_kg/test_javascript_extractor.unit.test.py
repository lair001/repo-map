import unittest

from repomap_kg.javascript import extract_javascript_file_observations


class JavaScriptExtractorUnitTests(unittest.TestCase):
    def test_extracts_imports_exports_functions_classes_and_references(self):
        content = (
            'import React, { useEffect } from "react";\n'
            'import { helper } from "./util.mjs";\n'
            'import "./styles.css";\n'
            'export { helper } from "./util.mjs";\n'
            "export function main() {\n"
            '  return fetch("https://example.invalid/api?token=fake-js-token");\n'
            "}\n"
            "class Runner {\n"
            "  start() {\n"
            "  }\n"
            "}\n"
            "const App = () => <main />;\n"
            "const COUNT = 3;\n"
        )

        observations = extract_javascript_file_observations(
            "src/index.js",
            content,
            repository_paths=frozenset(
                {
                    "src/index.js",
                    "src/util.mjs",
                    "src/styles.css",
                }
            ),
        )
        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {item.kind for item in observations}
        references = {
            (item.metadata.get("reference_kind"), item.target)
            for item in observations
            if item.kind == "js.reference"
        }

        self.assertEqual(observations[0].kind, "js.file")
        self.assertEqual(observations[0].target, "js.file:file%3Asrc%2Findex.js")
        self.assertEqual(observations[0].metadata["profile"], "react")
        self.assertIn("js.module", kinds)
        self.assertIn("js.import", kinds)
        self.assertIn("js.export", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.class", kinds)
        self.assertIn("js.method", kinds)
        self.assertIn("js.variable", kinds)
        self.assertIn("js.component", kinds)
        self.assertIn(("import", "external:js-package:react"), references)
        self.assertIn(("import", "file:src/util.mjs"), references)
        self.assertIn(("side_effect_import", "file:src/styles.css"), references)
        self.assertIn(("fetch", "external.url:https%3A%2F%2Fexample.invalid%2Fapi%3Ftoken%3DREDACTED"), references)
        self.assertNotIn("fake-js-token", payload)

    def test_detects_typescript_interfaces_types_enums_and_dynamic_imports(self):
        content = (
            "import type { Widget } from './types';\n"
            "export interface ServiceConfig { name: string }\n"
            "type Mode = 'fast' | 'safe';\n"
            "enum Status { Ready, Done }\n"
            "const loader = () => import(`./pages/${name}.tsx`);\n"
            "const LazyPanel = React.lazy(() => import('./Panel'));\n"
        )

        observations = extract_javascript_file_observations(
            "src/app.ts",
            content,
            repository_paths=frozenset(
                {
                    "src/app.ts",
                    "src/types.ts",
                    "src/Panel.tsx",
                }
            ),
        )
        kinds = {item.kind for item in observations}
        targets = {item.target for item in observations if item.kind == "js.reference"}
        dynamic = [
            item for item in observations
            if item.kind == "js.parse_error" and item.metadata.get("dynamic")
        ]

        self.assertEqual(observations[0].metadata["format"], "typescript")
        self.assertIn("js.interface", kinds)
        self.assertIn("js.type_alias", kinds)
        self.assertIn("js.enum", kinds)
        self.assertIn("file:src/types.ts", targets)
        self.assertIn("file:src/Panel.tsx", targets)
        self.assertTrue(dynamic)

    def test_detects_jest_suites_and_tests_without_execution(self):
        content = (
            "import { describe, expect, test } from '@jest/globals';\n"
            "describe('math helpers', () => {\n"
            "  test('adds numbers', () => {\n"
            "    expect(1 + 1).toBe(2);\n"
            "  });\n"
            "});\n"
        )

        observations = extract_javascript_file_observations(
            "src/jest/example.test.js",
            content,
        )
        test_suite = next(item for item in observations if item.kind == "js.test_suite")
        test_case = next(item for item in observations if item.kind == "js.test_case")
        expectation = next(
            item for item in observations if item.kind == "js.test_expectation"
        )

        self.assertEqual(test_suite.metadata["profile"], "jest")
        self.assertEqual(test_suite.metadata["test_framework"], "jest")
        self.assertEqual(test_suite.metadata["test_name_summary"], "math helpers")
        self.assertEqual(test_case.metadata["test_name_summary"], "adds numbers")
        self.assertTrue(test_case.target.startswith("js.test_case:"))
        self.assertEqual(expectation.metadata["expectation_count"], 1)

    def test_detects_react_angular_vue_and_report_asset_profiles(self):
        react = extract_javascript_file_observations(
            "src/react/App.jsx",
            (
                "import React, { useState } from 'react';\n"
                "export function App() {\n"
                "  const [count, setCount] = useState(0);\n"
                "  return <Route path=\"/home\" element={<Home />} />;\n"
                "}\n"
            ),
        )
        angular = extract_javascript_file_observations(
            "src/angular/app.component.ts",
            (
                "import { Component } from '@angular/core';\n"
                "@Component({ selector: 'app-root', templateUrl: './app.html', styleUrls: ['./app.css'] })\n"
                "export class AppComponent {}\n"
            ),
            repository_paths=frozenset(
                {
                    "src/angular/app.component.ts",
                    "src/angular/app.html",
                    "src/angular/app.css",
                }
            ),
        )
        vue = extract_javascript_file_observations(
            "src/vue/main.ts",
            "import { createApp, defineComponent } from 'vue';\nconst App = defineComponent({});\n",
        )
        report = extract_javascript_file_observations(
            "public/report.js",
            "export function renderReport() {}\n//# sourceMappingURL=report.js.map\n",
            repository_paths=frozenset({"public/report.js", "public/report.js.map"}),
        )

        self.assertIn("js.component", {item.kind for item in react})
        self.assertIn("js.hook", {item.kind for item in react})
        self.assertIn("js.route", {item.kind for item in react})
        self.assertEqual(angular[0].metadata["profile"], "angular")
        self.assertIn("file:src/angular/app.html", {item.target for item in angular if item.kind == "js.reference"})
        self.assertIn("file:src/angular/app.css", {item.target for item in angular if item.kind == "js.reference"})
        self.assertEqual(vue[0].metadata["profile"], "vue")
        self.assertEqual(report[0].metadata["profile"], "test_report_asset")
        self.assertIn(
            "file:public/report.js.map",
            {item.target for item in report if item.kind == "js.reference"},
        )

    def test_dynamic_constructs_and_secret_literals_are_safe(self):
        content = (
            'const apiToken = "fake-js-secret";\n'
            "const mod = require(name);\n"
            "const target = import(`./${name}.js`);\n"
            "eval('alert(1)');\n"
            "new Function('return secret')();\n"
            "const envValue = process.env.SECRET_TOKEN;\n"
        )

        observations = extract_javascript_file_observations("dynamic.js", content)
        payload = "\n".join(item.to_json_line() for item in observations)
        dynamic = [
            item for item in observations
            if item.metadata.get("dynamic") or item.metadata.get("redacted")
        ]
        variable = next(
            item for item in observations
            if item.kind == "js.variable" and item.name == "apiToken"
        )

        self.assertNotIn("fake-js-secret", payload)
        self.assertGreaterEqual(len(dynamic), 4)
        self.assertTrue(variable.metadata["redacted"])
        self.assertIn("js.parse_error", {item.kind for item in observations})


if __name__ == "__main__":
    unittest.main()
