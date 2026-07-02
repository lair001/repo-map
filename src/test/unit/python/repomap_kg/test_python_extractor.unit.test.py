import tempfile
import unittest
from pathlib import Path

from repomap_kg.python_extractor import (
    PythonModuleIndex,
    extract_python_file_observations,
    importable_module_name,
    module_name_from_suffix,
    package_roots,
    pyproject_package_roots,
)


class PythonExtractorUnitTests(unittest.TestCase):
    def test_importable_module_name_supports_src_main_package_layout(self):
        self.assertEqual(
            importable_module_name("src/main/python/repomap_kg/cli.py"),
            "repomap_kg.cli",
        )
        self.assertEqual(
            importable_module_name("src/main/python/repomap_kg/__init__.py"),
            "repomap_kg",
        )

    def test_importable_module_name_supports_src_test_python_layout(self):
        self.assertEqual(
            importable_module_name(
                "src/test/unit/python/repomap_kg/test_cli.unit.test.py"
            ),
            "repomap_kg.test_cli.unit.test",
        )
        self.assertEqual(
            importable_module_name(
                "src/test/int/python/repomap_kg/test_storage.int.test.py"
            ),
            "repomap_kg.test_storage.int.test",
        )

    def test_importable_module_name_supports_pyproject_package_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[tool.setuptools]\n"
                "package-dir = { \"\" = \"lib/python\" }\n",
                encoding="utf-8",
            )

            self.assertEqual(
                importable_module_name(
                    "lib/python/acme/app.py",
                    repository_root=root,
                ),
                "acme.app",
            )

    def test_module_name_helpers_handle_init_files_and_non_python_files(self):
        self.assertEqual(module_name_from_suffix("pkg/__init__.py"), "pkg")
        self.assertIsNone(module_name_from_suffix("__init__.py"))
        self.assertIsNone(importable_module_name("README.md"))

    def test_pyproject_package_roots_ignore_missing_or_malformed_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(pyproject_package_roots(root), ())

            (root / "pyproject.toml").write_text("[tool.setuptools\n")
            self.assertEqual(pyproject_package_roots(root), ())

    def test_package_roots_include_defaults_pyproject_and_test_layouts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[tool.setuptools]\n"
                "package-dir = { \"\" = \"lib/python\" }\n",
                encoding="utf-8",
            )

            roots = package_roots(root)

        self.assertIn("src/main/python", roots)
        self.assertIn("lib/python", roots)
        self.assertIn("src/test/unit/python", roots)
        self.assertIn("src/test/int/python", roots)

    def test_python_module_index_discovers_known_modules_from_paths(self):
        index = PythonModuleIndex.from_python_paths(
            [
                "src/main/python/pkg/__init__.py",
                "src/main/python/pkg/app.py",
                "README.md",
            ]
        )

        self.assertTrue(index.has_module("pkg"))
        self.assertTrue(index.has_module("pkg.app"))
        self.assertEqual(index.module_to_path["pkg.app"], "src/main/python/pkg/app.py")
        self.assertEqual(index.path_to_module["src/main/python/pkg/__init__.py"], "pkg")

    def test_extract_python_file_observations_finds_symbols_and_imports(self):
        content = (
            "import os\n"
            "from repomap_kg import storage as storage_mod\n"
            "from . import sibling\n"
            "from .subpackage import helper\n"
            "\n"
            "class Demo:\n"
            "    def method(self):\n"
            "        return storage_mod\n"
            "\n"
            "async def build():\n"
            "    return os.name\n"
        )
        module_index = PythonModuleIndex.from_modules(
            {
                "repomap_kg.cli": "src/main/python/repomap_kg/cli.py",
                "repomap_kg.storage": "src/main/python/repomap_kg/storage.py",
                "repomap_kg.sibling": "src/main/python/repomap_kg/sibling.py",
                "repomap_kg.subpackage.helper": (
                    "src/main/python/repomap_kg/subpackage/helper.py"
                ),
            }
        )

        observations = extract_python_file_observations(
            "src/main/python/repomap_kg/cli.py",
            content,
            module_index=module_index,
        )

        self.assertEqual(
            [observation.kind for observation in observations],
            [
                "python.module",
                "python.import",
                "python.import",
                "python.import",
                "python.import",
                "python.class",
                "python.method",
                "python.function",
            ],
        )
        self.assertEqual(observations[0].name, "repomap_kg.cli")
        self.assertEqual(observations[0].start_line, 1)
        self.assertEqual(observations[0].end_line, 11)

        imports = [item for item in observations if item.kind == "python.import"]
        self.assertEqual(
            [(item.name, item.target, item.metadata["resolution"]) for item in imports],
            [
                ("os", "external:python.module:os", "external"),
                (
                    "repomap_kg.storage",
                    "python.module:repomap_kg.storage",
                    "local",
                ),
                (
                    "repomap_kg.sibling",
                    "python.module:repomap_kg.sibling",
                    "local",
                ),
                (
                    "repomap_kg.subpackage.helper",
                    "python.module:repomap_kg.subpackage.helper",
                    "local",
                ),
            ],
        )

        symbol_targets = {
            observation.kind: observation.target
            for observation in observations
            if observation.kind in {"python.class", "python.function"}
        }
        self.assertEqual(
            symbol_targets,
            {
                "python.class": "python.class:repomap_kg.cli:Demo",
                "python.function": "python.function:repomap_kg.cli:build",
            },
        )
        method = next(item for item in observations if item.kind == "python.method")
        self.assertEqual(method.target, "python.method:repomap_kg.cli:Demo:method")
        self.assertEqual(method.metadata["class"], "Demo")

    def test_extract_python_file_observations_reports_unresolved_relative_import(self):
        observations = extract_python_file_observations(
            "scratch.py",
            "from . import sibling\n",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual([item.kind for item in observations], ["python.module", "python.import"])
        import_observation = observations[1]
        self.assertEqual(
            import_observation.target,
            "unknown:python.module:missing-package-context",
        )
        self.assertEqual(import_observation.metadata["resolution"], "unknown")

    def test_extract_python_file_observations_handles_local_import_and_from_fallbacks(self):
        module_index = PythonModuleIndex.from_modules(
            {
                "pkg": "src/main/python/pkg/__init__.py",
                "pkg.lib.helper": "src/main/python/pkg/lib/helper.py",
                "pkg.sibling": "src/main/python/pkg/sibling.py",
            }
        )
        content = (
            "import pkg.lib.helper\n"
            "from pkg import CONSTANT\n"
            "from . import missing\n"
            "from . import *\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/pkg/app.py",
            content,
            module_index=module_index,
        )
        imports = [item for item in observations if item.kind == "python.import"]

        self.assertEqual(
            [(item.name, item.target, item.metadata["resolution"]) for item in imports],
            [
                (
                    "pkg.lib.helper",
                    "python.module:pkg.lib.helper",
                    "local",
                ),
                ("pkg", "python.module:pkg", "local"),
                (
                    "pkg.missing",
                    "unknown:python.module:missing-module",
                    "unknown",
                ),
                (
                    "pkg",
                    "python.module:pkg",
                    "local",
                ),
            ],
        )

    def test_extract_python_file_observations_handles_external_from_and_level_escape(self):
        content = (
            "from pathlib import Path\n"
            "from .. import missing\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/pkg/app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )
        imports = [item for item in observations if item.kind == "python.import"]

        self.assertEqual(
            [(item.name, item.target, item.metadata["resolution"]) for item in imports],
            [
                ("pathlib", "external:python.module:pathlib", "external"),
                (
                    "missing",
                    "unknown:python.module:missing-package-context",
                    "unknown",
                ),
            ],
        )

    def test_extract_python_file_observations_captures_decorators_bases_and_async(self):
        content = (
            "class Base:\n"
            "    pass\n"
            "\n"
            "@decorator\n"
            "class Service(Base):\n"
            "    @classmethod\n"
            "    async def run(cls):\n"
            "        return cls\n"
            "\n"
            "@decorator\n"
            "async def build():\n"
            "    return Service\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/pkg/app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        service = next(
            item for item in observations
            if item.kind == "python.class" and item.name == "Service"
        )
        method = next(item for item in observations if item.kind == "python.method")
        function = next(
            item for item in observations
            if item.kind == "python.function" and item.name == "build"
        )
        self.assertEqual(service.metadata["bases"], ["Base"])
        self.assertEqual(service.metadata["decorators"], ["decorator"])
        self.assertTrue(method.metadata["async"])
        self.assertEqual(method.metadata["decorators"], ["classmethod"])
        self.assertTrue(function.metadata["async"])
        self.assertEqual(function.metadata["decorators"], ["decorator"])

    def test_package_roots_ignore_non_mapping_package_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[tool.setuptools]\npackage-dir = \"src\"\n",
                encoding="utf-8",
            )

            self.assertEqual(pyproject_package_roots(root), ())

    def test_extract_python_file_observations_ignores_non_importable_paths(self):
        observations = extract_python_file_observations(
            "README.md",
            "not python",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual(observations, ())

    def test_extract_python_file_observations_handles_empty_module(self):
        observations = extract_python_file_observations(
            "src/main/python/empty.py",
            "",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].kind, "python.module")
        self.assertEqual(observations[0].end_line, 1)

    def test_extract_python_file_observations_reports_syntax_errors_without_source(self):
        observations = extract_python_file_observations(
            "src/main/python/broken.py",
            "def nope(:\n",
            module_index=PythonModuleIndex.empty(),
        )

        self.assertEqual([item.kind for item in observations], ["python.parse_error"])
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-python")
        self.assertNotIn("def nope", str(observations[0].metadata))

    def test_unittest_and_pytest_profile_observations_are_static_and_bounded(self):
        content = (
            "import unittest\n"
            "import pytest\n"
            "\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        self.value = 1\n"
            "\n"
            "    def test_unit(self):\n"
            "        self.assertEqual(self.value, 1)\n"
            "        self.assertTrue(self.value)\n"
            "\n"
            "@pytest.fixture\n"
            "def client():\n"
            "    return object()\n"
            "\n"
            "@pytest.mark.parametrize('value', [1, 2])\n"
            "def test_pytest(client, value):\n"
            "    assert value in {1, 2}\n"
            "\n"
            "class TestFeature:\n"
            "    @pytest.mark.slow\n"
            "    def test_method(self):\n"
            "        assert True\n"
        )

        observations = extract_python_file_observations(
            "src/test/unit/python/pkg/test_sample.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )
        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        test_file = next(item for item in observations if item.kind == "python.test_file")
        unittest_case = next(
            item for item in observations if item.kind == "python.unittest_case"
        )
        fixtures = [item for item in observations if item.kind == "python.pytest_fixture"]
        pytest_tests = [item for item in observations if item.kind == "python.pytest_test"]
        assertions = [item for item in observations if item.kind == "python.test_assertion"]

        self.assertTrue(
            {
                "python.module",
                "python.class",
                "python.method",
                "python.function",
                "python.test_file",
                "python.unittest_case",
                "python.test_method",
                "python.test_function",
                "python.pytest_test",
                "python.pytest_fixture",
                "python.test_parametrize",
                "python.test_assertion",
            }.issubset(kinds)
        )
        self.assertEqual(test_file.metadata["profile"], "python")
        self.assertIn("pytest", test_file.metadata["test_frameworks"])
        self.assertIn("unittest", test_file.metadata["test_frameworks"])
        self.assertEqual(unittest_case.metadata["class_name"], "SampleTest")
        self.assertEqual(unittest_case.metadata["test_method_count"], 1)
        self.assertEqual(fixtures[0].metadata["fixture_name"], "client")
        self.assertEqual({item.metadata["test_name"] for item in pytest_tests}, {"test_pytest", "test_method"})
        self.assertGreaterEqual(sum(item.metadata["assertion_count"] for item in assertions), 4)
        self.assertNotIn("fake", payload)

    def test_flask_profile_observations_capture_static_routes_and_redactions(self):
        content = (
            "from flask import Flask, Blueprint\n"
            "\n"
            "app = Flask(__name__)\n"
            "bp = Blueprint('admin', __name__)\n"
            "app.config['SECRET_KEY'] = 'fake-flask-secret-value'\n"
            "\n"
            "@app.route('/users/<user_id>', methods=['GET', 'POST'])\n"
            "def user_detail():\n"
            "    return 'ok'\n"
            "\n"
            "@bp.post('/admin/token')\n"
            "def create_token():\n"
            "    return 'ok'\n"
            "\n"
            "def health_handler():\n"
            "    return 'ok'\n"
            "\n"
            "app.add_url_rule('/health', 'health', health_handler, methods=['GET'])\n"
            "\n"
            "@app.route(prefix + '/dynamic')\n"
            "def dynamic_route():\n"
            "    return 'ok'\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/service/flask_app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        routes = [item for item in observations if item.kind == "python.flask_route"]
        route_by_name = {item.name: item for item in routes}
        references = [item for item in observations if item.kind == "python.reference"]
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "dynamic-python-web-route"
        ]

        self.assertTrue(
            {
                "python.flask_app",
                "python.flask_blueprint",
                "python.flask_route",
                "python.reference",
                "python.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(route_by_name["user_detail"].metadata["route_path"], "/users/<user_id>")
        self.assertEqual(route_by_name["user_detail"].metadata["http_methods"], ["GET", "POST"])
        self.assertEqual(route_by_name["create_token"].metadata["http_methods"], ["POST"])
        self.assertEqual(route_by_name["health_handler"].metadata["route_path"], "/health")
        self.assertEqual(route_by_name["dynamic_route"].metadata["route_path_kind"], "dynamic")
        self.assertTrue(diagnostics)
        self.assertTrue(any(item.metadata["reference_kind"] == "flask_route_handler" for item in references))
        self.assertNotIn("fake-flask-secret-value", payload)

    def test_fastapi_profile_observations_capture_routes_dependencies_and_redactions(self):
        content = (
            "from fastapi import FastAPI, APIRouter, Depends\n"
            "\n"
            "app = FastAPI(title='Fixture')\n"
            "router = APIRouter()\n"
            "\n"
            "def require_user(api_key='fake-fastapi-secret-default'):\n"
            "    return api_key\n"
            "\n"
            "@app.get('/items/{item_id}', response_model=Item, tags=['items'], summary='read an item safely')\n"
            "async def read_item(item_id: str, user=Depends(require_user)):\n"
            "    return {'item_id': item_id}\n"
            "\n"
            "@router.api_route('/bulk', methods=['POST', 'PUT'], description='bulk operation details')\n"
            "def bulk_items():\n"
            "    return []\n"
            "\n"
            "app.include_router(router)\n"
            "\n"
            "@app.get(prefix + '/dynamic')\n"
            "def dynamic_route():\n"
            "    return {}\n"
        )

        observations = extract_python_file_observations(
            "src/main/python/service/fastapi_app.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        routes = [item for item in observations if item.kind == "python.fastapi_route"]
        route_by_name = {item.name: item for item in routes}
        dependencies = [
            item for item in observations if item.kind == "python.fastapi_dependency"
        ]
        references = [item for item in observations if item.kind == "python.reference"]
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "dynamic-python-web-route"
        ]

        self.assertTrue(
            {
                "python.fastapi_app",
                "python.fastapi_router",
                "python.fastapi_route",
                "python.fastapi_dependency",
                "python.reference",
                "python.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(route_by_name["read_item"].metadata["route_path"], "/items/{item_id}")
        self.assertEqual(route_by_name["read_item"].metadata["http_methods"], ["GET"])
        self.assertTrue(route_by_name["read_item"].metadata["summary_present"])
        self.assertIn("summary_sha256", route_by_name["read_item"].metadata)
        self.assertNotIn("read an item safely", payload)
        self.assertEqual(route_by_name["bulk_items"].metadata["http_methods"], ["POST", "PUT"])
        self.assertEqual(route_by_name["dynamic_route"].metadata["route_path_kind"], "dynamic")
        self.assertTrue(dependencies)
        self.assertTrue(any(item.metadata["reference_kind"] == "fastapi_include_router" for item in references))
        self.assertTrue(diagnostics)
        self.assertNotIn("fake-fastapi-secret-default", payload)

    def test_django_profile_observations_capture_urls_models_settings_and_redactions(self):
        url_content = (
            "from django.urls import path, re_path, include\n"
            "from . import views\n"
            "\n"
            "urlpatterns = [\n"
            "    path('users/', views.user_list, name='users'),\n"
            "    re_path(r'^items/(?P<slug>[-\\\\w]+)/$', views.ItemView.as_view()),\n"
            "    path('api/', include('fixture.api.urls')),\n"
            "    path(dynamic_prefix, views.dynamic_view),\n"
            "]\n"
        )
        model_content = (
            "from django.db import models\n"
            "from django.apps import AppConfig\n"
            "\n"
            "class InventoryItem(models.Model):\n"
            "    name = models.CharField(max_length=64)\n"
            "    active = models.BooleanField(default=True)\n"
            "\n"
            "class InventoryConfig(AppConfig):\n"
            "    name = 'inventory'\n"
        )
        settings_content = (
            "SECRET_KEY = 'fake-django-secret-key'\n"
            "DATABASE_URL = 'postgres://user:fake-db-secret@example.invalid/app'\n"
            "INSTALLED_APPS = ['inventory']\n"
        )

        url_observations = extract_python_file_observations(
            "src/main/python/project/urls.py",
            url_content,
            module_index=PythonModuleIndex.empty(),
        )
        model_observations = extract_python_file_observations(
            "src/main/python/project/app/models.py",
            model_content,
            module_index=PythonModuleIndex.empty(),
        )
        settings_observations = extract_python_file_observations(
            "src/main/python/project/settings.py",
            settings_content,
            module_index=PythonModuleIndex.empty(),
        )
        observations = (*url_observations, *model_observations, *settings_observations)

        kinds = {item.kind for item in observations}
        payload = "\n".join(item.to_json_line() for item in observations)
        patterns = [item for item in observations if item.kind == "python.django_urlpattern"]
        pattern_by_kind = {item.metadata["urlpattern_kind"]: item for item in patterns}
        models = [item for item in observations if item.kind == "python.django_model"]
        setting_refs = [
            item for item in observations if item.kind == "python.django_setting_reference"
        ]
        users_path = next(
            item
            for item in patterns
            if item.metadata.get("route_path") == "users/"
        )
        regex_path = next(
            item
            for item in patterns
            if item.metadata["urlpattern_kind"] == "re_path"
        )
        include_path = next(
            item
            for item in patterns
            if item.metadata["urlpattern_kind"] == "include"
        )
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "dynamic-python-web-route"
        ]

        self.assertTrue(
            {
                "python.django_app",
                "python.django_urlpattern",
                "python.django_view",
                "python.django_model",
                "python.django_setting_reference",
                "python.reference",
                "python.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(users_path.metadata["route_path"], "users/")
        self.assertEqual(regex_path.metadata["route_path_kind"], "regex_literal")
        self.assertEqual(include_path.metadata["include_target"], "fixture.api.urls")
        self.assertEqual(models[0].metadata["model_name"], "InventoryItem")
        self.assertEqual(models[0].metadata["model_field_count"], 2)
        self.assertIn("SECRET_KEY", {item.name for item in setting_refs})
        self.assertTrue(diagnostics)
        self.assertNotIn("fake-django-secret-key", payload)
        self.assertNotIn("fake-db-secret", payload)

    def test_python_web_profile_observations_are_bounded_with_safe_diagnostics(self):
        content = "from flask import Flask\napp = Flask(__name__)\n"
        for index in range(80):
            content += (
                f"@app.get('/route-{index}')\n"
                f"def route_{index}():\n"
                "    return 'ok'\n"
            )

        observations = extract_python_file_observations(
            "src/main/python/service/many_routes.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )

        routes = [item for item in observations if item.kind == "python.flask_route"]
        diagnostics = [
            item
            for item in observations
            if item.kind == "python.parse_error"
            and item.metadata["error_kind"] == "python-web-profile-limit"
        ]

        self.assertLessEqual(len(routes), 64)
        self.assertTrue(diagnostics)
        self.assertNotIn("route_79", "\n".join(item.to_json_line() for item in diagnostics))

    def test_python_web_profile_redacts_credentialed_routes_and_secret_assignments(self):
        content = (
            "from flask import Flask\n"
            "from fastapi import FastAPI\n"
            "\n"
            "app = Flask(__name__)\n"
            "api = FastAPI()\n"
            "API_TOKEN = 'fake-web-assignment-secret'\n"
            "\n"
            "@app.route('https://user:fake-route-secret@example.invalid/path')\n"
            "def unsafe_route():\n"
            "    return 'redacted'\n"
            "\n"
            "@api.post('/created', status_code=201)\n"
            "def create_item():\n"
            "    return {}\n"
        )
        settings_content = "DEBUG = True\n"

        observations = extract_python_file_observations(
            "src/main/python/service/mixed_web.py",
            content,
            module_index=PythonModuleIndex.empty(),
        )
        settings_observations = extract_python_file_observations(
            "src/main/python/service/settings.py",
            settings_content,
            module_index=PythonModuleIndex.empty(),
        )
        payload = "\n".join(
            item.to_json_line()
            for item in (*observations, *settings_observations)
        )
        flask_route = next(
            item for item in observations if item.kind == "python.flask_route"
        )
        fastapi_route = next(
            item for item in observations if item.kind == "python.fastapi_route"
        )
        setting = next(
            item
            for item in settings_observations
            if item.kind == "python.django_setting_reference"
        )

        self.assertEqual(flask_route.metadata["route_path_kind"], "redacted")
        self.assertTrue(flask_route.metadata["redacted"])
        self.assertEqual(fastapi_route.metadata["status_code"], 201)
        self.assertEqual(setting.name, "DEBUG")
        self.assertFalse(setting.metadata["redacted"])
        self.assertIn("secret-like-assignment", payload)
        self.assertNotIn("fake-web-assignment-secret", payload)
        self.assertNotIn("fake-route-secret", payload)


if __name__ == "__main__":
    unittest.main()
