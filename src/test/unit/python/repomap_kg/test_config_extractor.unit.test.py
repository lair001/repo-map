import json
import unittest

from repomap_kg.config_extractor import (
    extract_config_file_observations,
    json_pointer,
)


def observations_format(observations):
    return observations[0].metadata["format"]


class ConfigExtractorUnitTests(unittest.TestCase):
    def test_python_requirements_emit_package_references_and_safe_redactions(self):
        observations = extract_config_file_observations(
            "requirements.txt",
            (
                "requests>=2.31,<3\n"
                "fastapi[standard]==0.111.0; python_version >= '3.11'\n"
                "-r dev-requirements.txt\n"
                "-c ../outside.txt\n"
                "-e ./localpkg\n"
                "example @ https://packages.example.invalid/example-1.0.tar.gz\n"
                "--index-url https://user:fake-python-index-secret@packages.example.invalid/simple\n"
                "secret-package @ https://user:fake-python-direct-secret@packages.example.invalid/secret.tar.gz\n"
                "@@not a requirement@@\n"
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        requirements = [
            item for item in observations if item.kind == "python.requirement"
        ]
        references = [item for item in observations if item.kind == "python.reference"]
        redactions = [item for item in observations if item.kind == "python.redaction"]
        parse_errors = [
            item for item in observations if item.kind == "python.parse_error"
        ]

        self.assertIn("python.package_file", kinds)
        self.assertEqual(
            {
                item.metadata["package_name"]
                for item in requirements
                if "package_name" in item.metadata
            },
            {"requests", "fastapi", "localpkg", "example", "secret-package"},
        )
        fastapi = next(
            item
            for item in requirements
            if item.metadata.get("package_name") == "fastapi"
        )
        self.assertEqual(fastapi.metadata["extras"], ["standard"])
        self.assertEqual(
            fastapi.metadata["environment_marker"],
            "python_version >= '3.11'",
        )
        self.assertIn(
            ("include_file", "file:dev-requirements.txt"),
            {(item.metadata["reference_kind"], item.target) for item in references},
        )
        self.assertIn(
            ("local_path", "file:localpkg"),
            {(item.metadata["reference_kind"], item.target) for item in references},
        )
        self.assertIn(
            "repo-escaping-requirement-reference",
            {item.metadata["error_kind"] for item in parse_errors},
        )
        self.assertIn(
            "malformed-python-requirement",
            {item.metadata["error_kind"] for item in parse_errors},
        )
        self.assertTrue(any(item.metadata["not_fetched"] for item in references))
        self.assertTrue(redactions)
        self.assertNotIn("fake-python-index-secret", payload)
        self.assertNotIn("fake-python-direct-secret", payload)
        self.assertNotIn("user:fake", payload)

    def test_pyproject_emits_python_profile_observations_and_keeps_toml_config(self):
        observations = extract_config_file_observations(
            "pyproject.toml",
            (
                "[project]\n"
                'name = "fixture-python-app"\n'
                'version = "0.1.0"\n'
                'dynamic = ["description"]\n'
                "dependencies = [\n"
                '  "requests>=2.31",\n'
                '  "fastapi[standard]>=0.111; python_version >= \'3.11\'",\n'
                '  "secret-package @ https://user:fake-pyproject-secret@packages.example.invalid/secret.tar.gz",\n'
                "]\n"
                "\n"
                "[project.optional-dependencies]\n"
                'test = ["pytest>=8"]\n'
                "\n"
                "[project.scripts]\n"
                'fixture-tool = "fixture_app.cli:main"\n'
                "\n"
                '[project.entry-points."fixture.plugins"]\n'
                'demo = "fixture_app.plugins:Demo"\n'
                "\n"
                "[build-system]\n"
                'requires = ["setuptools>=69", "wheel"]\n'
                'build-backend = "setuptools.build_meta"\n'
                "\n"
                "[tool.pytest.ini_options]\n"
                'testpaths = ["tests"]\n'
                "\n"
                "[tool.ruff]\n"
                "line-length = 88\n"
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        pyproject = next(item for item in observations if item.kind == "python.pyproject")
        build_system = next(
            item for item in observations if item.kind == "python.build_system"
        )
        tool_sections = [
            item.metadata["tool_name"]
            for item in observations
            if item.kind == "python.tool_config"
        ]
        requirements = [
            item for item in observations if item.kind == "python.requirement"
        ]
        entry_points = [
            item for item in observations if item.kind == "python.entry_point"
        ]

        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertEqual(pyproject.metadata["project_name"], "fixture-python-app")
        self.assertEqual(pyproject.metadata["project_version"], "0.1.0")
        self.assertEqual(pyproject.metadata["dynamic_metadata"], ["description"])
        self.assertEqual(build_system.metadata["build_backend"], "setuptools.build_meta")
        self.assertIn("pytest", tool_sections)
        self.assertIn("ruff", tool_sections)
        self.assertIn(
            ("requests", "project.dependencies"),
            {
                (item.metadata["package_name"], item.metadata["dependency_group"])
                for item in requirements
                if "package_name" in item.metadata
            },
        )
        self.assertIn(
            ("pytest", "project.optional-dependencies.test"),
            {
                (item.metadata["package_name"], item.metadata["dependency_group"])
                for item in requirements
                if "package_name" in item.metadata
            },
        )
        self.assertIn(
            ("fixture-tool", "project.scripts"),
            {
                (item.metadata["entry_point_name"], item.metadata["entry_point_group"])
                for item in entry_points
            },
        )
        self.assertIn("python.redaction", kinds)
        self.assertNotIn("fake-pyproject-secret", payload)
        self.assertNotIn("user:fake", payload)

    def test_malformed_pyproject_emits_generic_and_python_parse_diagnostics(self):
        observations = extract_config_file_observations(
            "pyproject.toml",
            "[project\nname = 'broken'\n",
        )

        kinds = {item.kind for item in observations}
        python_error = next(
            item for item in observations if item.kind == "python.parse_error"
        )

        self.assertIn("config.parse_error", kinds)
        self.assertEqual(
            python_error.metadata["error_kind"],
            "malformed-pyproject-toml",
        )
        self.assertNotIn("broken", str(python_error.metadata))

    def test_package_json_emits_ecosystem_profile_observations_and_redacts_scripts(self):
        observations = extract_config_file_observations(
            "package.json",
            json.dumps(
                {
                    "name": "@example/app",
                    "version": "1.2.3",
                    "private": True,
                    "type": "module",
                    "packageManager": "pnpm@9.1.0",
                    "scripts": {
                        "test": "jest --runInBand",
                        "deploy": "TOKEN=fake-package-secret npm publish",
                    },
                    "dependencies": {
                        "express": "^4.18.0",
                        "next": "14.0.0",
                        "react": "18.2.0",
                    },
                    "devDependencies": {"jest": "^29.0.0"},
                    "peerDependencies": {"jquery": "^3.7.0"},
                    "optionalDependencies": {"fsevents": "^2.3.0"},
                    "engines": {"node": ">=20"},
                    "workspaces": ["packages/*"],
                    "bin": {"example": "bin/example.js"},
                    "main": "dist/index.js",
                    "module": "dist/index.mjs",
                    "types": "dist/index.d.ts",
                    "exports": {"." : "./dist/index.js"},
                    "imports": {"#config": "./src/config.js"},
                    "repository": {"url": "https://example.invalid/repo.git"},
                    "homepage": "https://example.invalid/app",
                    "bugs": {"url": "https://example.invalid/issues"},
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        package = next(item for item in observations if item.kind == "npm.package")
        scripts = [item for item in observations if item.kind == "npm.script"]
        dependencies = [item for item in observations if item.kind == "npm.dependency"]
        hints = [item for item in observations if item.kind == "ecosystem.framework_hint"]
        paths = {item.metadata["pointer"]: item for item in observations if item.kind == "config.path"}

        self.assertIn("config.document", kinds)
        self.assertIn("ecosystem.config_profile", kinds)
        self.assertEqual(package.metadata["package_name"], "@example/app")
        self.assertEqual(package.metadata["package_version"], "1.2.3")
        self.assertTrue(package.metadata["private"])
        self.assertEqual(package.metadata["package_manager"], "pnpm@9.1.0")
        self.assertIn("scripts", package.metadata["declared_sections"])
        self.assertIn("workspaces", package.metadata["declared_sections"])
        self.assertIn(
            ("express", "dependencies"),
            {
                (item.metadata["dependency_name"], item.metadata["dependency_group"])
                for item in dependencies
            },
        )
        self.assertIn(
            ("jquery", "peerDependencies"),
            {
                (item.metadata["dependency_name"], item.metadata["dependency_group"])
                for item in dependencies
            },
        )
        self.assertIn(
            ("next", "package-dependency"),
            {
                (item.metadata["framework"], item.metadata["hint_reason"])
                for item in hints
            },
        )
        self.assertIn(
            ("test", "jest"),
            {
                (item.metadata["script_name"], item.metadata["command_summary"])
                for item in scripts
            },
        )
        deploy = next(item for item in scripts if item.metadata["script_name"] == "deploy")
        self.assertTrue(deploy.metadata["redacted"])
        self.assertEqual(deploy.metadata["redaction_reason"], "secret-prone-script")
        self.assertTrue(paths["/scripts/deploy"].metadata["redacted"])
        self.assertNotIn("fake-package-secret", payload)
        self.assertNotIn("TOKEN=", payload)

    def test_typescript_angular_jest_nest_and_playwright_json_profiles(self):
        cases = [
            (
                "tsconfig.json",
                {
                    "extends": "./tsconfig.base.json",
                    "compilerOptions": {
                        "baseUrl": ".",
                        "paths": {"@app/*": ["src/app/*"]},
                        "jsx": "react-jsx",
                    },
                    "references": [{"path": "./packages/app"}],
                },
                {"typescript.config", "typescript.reference"},
            ),
            (
                "angular.json",
                {
                    "projects": {
                        "web": {
                            "root": "apps/web",
                            "sourceRoot": "apps/web/src",
                            "architect": {"build": {"builder": "@angular/build:application"}},
                        }
                    }
                },
                {"angular.project", "angular.target"},
            ),
            (
                "nest-cli.json",
                {"sourceRoot": "src", "collection": "@nestjs/schematics"},
                {"nest.config"},
            ),
            (
                "jest.config.json",
                {
                    "testEnvironment": "node",
                    "testMatch": ["**/*.test.ts"],
                    "setupFilesAfterEnv": ["./test/setup.ts"],
                },
                {"jest.config"},
            ),
            (
                "playwright.config.json",
                {
                    "testDir": "./tests/e2e",
                    "projects": [{"name": "chromium"}, {"name": "webkit"}],
                    "reporter": [["html", {"outputFolder": "playwright-report"}]],
                },
                {"playwright.config"},
            ),
        ]

        for path, document, expected_kinds in cases:
            with self.subTest(path=path):
                observations = extract_config_file_observations(path, json.dumps(document))
                kinds = {observation.kind for observation in observations}
                profiles = [
                    item
                    for item in observations
                    if item.kind == "ecosystem.config_profile"
                ]

                self.assertTrue(expected_kinds.issubset(kinds))
                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0].metadata["format"], "json")
                self.assertIn("profile", profiles[0].metadata)
                self.assertIn("config.document", kinds)
                self.assertIn("config.path", kinds)

    def test_terraform_json_emits_static_profile_observations_and_references(self):
        observations = extract_config_file_observations(
            "infra/main.tf.json",
            json.dumps(
                {
                    "terraform": {
                        "required_version": ">= 1.6.0",
                        "required_providers": {
                            "aws": {
                                "source": "hashicorp/aws",
                                "version": "~> 5.0",
                            }
                        },
                        "backend": {
                            "s3": {
                                "bucket": "example-state",
                                "key": "state/app.tfstate",
                            }
                        },
                    },
                    "provider": {"aws": {"region": "us-east-1"}},
                    "resource": {
                        "aws_s3_bucket": {
                            "app": {
                                "bucket": "example-app",
                                "secret_key": "fake-terraform-secret",
                            }
                        }
                    },
                    "data": {"aws_caller_identity": {"current": {}}},
                    "module": {"vpc": {"source": "terraform-aws-modules/vpc/aws"}},
                    "variable": {"region": {"type": "string"}},
                    "output": {"bucket_name": {"value": "${aws_s3_bucket.app.id}"}},
                    "locals": {"name": "app"},
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        references = [item for item in observations if item.kind == "terraform.reference"]
        resource = next(item for item in observations if item.kind == "terraform.resource")
        required_provider = next(
            item for item in observations if item.kind == "terraform.required_provider"
        )

        self.assertTrue(
            {
                "terraform.file",
                "terraform.required_version",
                "terraform.required_provider",
                "terraform.backend",
                "terraform.provider",
                "terraform.resource",
                "terraform.data_source",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.local",
                "terraform.reference",
            }.issubset(kinds)
        )
        self.assertEqual(resource.metadata["resource_type"], "aws_s3_bucket")
        self.assertEqual(resource.metadata["resource_name"], "app")
        self.assertEqual(required_provider.metadata["provider_source"], "hashicorp/aws")
        self.assertIn(
            ("provider_source", "external:terraform.provider:hashicorp%2Faws"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertIn(
            ("module_source", "external:terraform.module:terraform-aws-modules%2Fvpc%2Faws"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertNotIn("fake-terraform-secret", payload)

    def test_terraform_tfvars_json_redacts_all_values_by_default(self):
        observations = extract_config_file_observations(
            "terraform.tfvars.json",
            json.dumps(
                {
                    "region": "us-east-1",
                    "replicas": 3,
                    "tags": {"service": "api"},
                    "db_password": "fake-tfvars-secret",
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        variables = [item for item in observations if item.kind == "terraform.variable"]
        paths = {item.metadata["pointer"]: item for item in observations if item.kind == "config.path"}

        self.assertEqual({item.metadata["variable_name"] for item in variables}, {"region", "replicas", "tags", "db_password"})
        self.assertTrue(all(item.metadata["redacted"] for item in variables))
        self.assertEqual(
            {item.metadata["value_type"] for item in variables},
            {"string", "number", "object"},
        )
        self.assertTrue(paths["/region"].metadata["redacted"])
        self.assertTrue(paths["/tags"].metadata["redacted"])
        self.assertNotIn("us-east-1", payload)
        self.assertNotIn("api", payload)
        self.assertNotIn("fake-tfvars-secret", payload)

    def test_terraform_hcl_emits_static_profile_observations_and_references(self):
        observations = extract_config_file_observations(
            "infra/main.tf",
            """
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket = "fixture-state"
    access_key = "fake-tfhcl-backend-secret"
  }
}

provider "aws" {
  alias = "primary"
  region = "us-east-1"
  secret_key = "fake-tfhcl-provider-secret"
}

resource "aws_s3_bucket" "app" {
  bucket = "fixture-app"
  count = 1
  depends_on = [aws_iam_role.app]
  provider = aws.primary

  lifecycle {
    prevent_destroy = true
  }

  provisioner "local-exec" {
    command = "echo static-only"
  }
}

data "aws_caller_identity" "current" {}

module "vpc" {
  source = "./modules/vpc"
}

module "remote" {
  source = "git::https://user:fake-tfhcl-module-secret@example.invalid/org/mod.git"
}

variable "region" {
  type = string
  default = "us-east-1"
  description = "Deployment region"
  validation {
    condition = true
    error_message = "ok"
  }
}

output "bucket_name" {
  value = aws_s3_bucket.app.id
  sensitive = true
  description = "Bucket name"
}

locals {
  name = "app"
  api_token = "fake-tfhcl-local-secret"
}

moved {
  from = aws_s3_bucket.old
  to = aws_s3_bucket.app
}

import {
  to = aws_s3_bucket.imported
  id = "fake-tfhcl-import-secret"
}

removed {
  from = aws_s3_bucket.legacy
}

check "health" {
  assert {
    condition = true
    error_message = "healthy"
  }
}
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        references = [item for item in observations if item.kind == "terraform.reference"]
        resource = next(item for item in observations if item.kind == "terraform.resource")
        local_module = next(
            item
            for item in observations
            if item.kind == "terraform.module"
            and item.metadata["module_name"] == "vpc"
        )
        remote_module = next(
            item
            for item in observations
            if item.kind == "terraform.module"
            and item.metadata["module_name"] == "remote"
        )
        variable = next(item for item in observations if item.kind == "terraform.variable")
        output = next(item for item in observations if item.kind == "terraform.output")

        self.assertTrue(
            {
                "terraform.file",
                "terraform.block",
                "terraform.required_version",
                "terraform.required_provider",
                "terraform.backend",
                "terraform.provider",
                "terraform.resource",
                "terraform.data_source",
                "terraform.module",
                "terraform.variable",
                "terraform.output",
                "terraform.local",
                "terraform.reference",
                "terraform.moved",
                "terraform.import",
                "terraform.removed",
                "terraform.check",
                "terraform.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(resource.metadata["resource_type"], "aws_s3_bucket")
        self.assertEqual(resource.metadata["resource_name"], "app")
        self.assertEqual(resource.metadata["provider_prefix"], "aws")
        self.assertTrue(resource.metadata["count_present"])
        self.assertTrue(resource.metadata["lifecycle_present"])
        self.assertTrue(resource.metadata["provisioner_present"])
        self.assertEqual(local_module.target, "file:infra/modules/vpc")
        self.assertTrue(remote_module.metadata["not_fetched"])
        self.assertTrue(remote_module.metadata["redacted"])
        self.assertEqual(variable.metadata["variable_name"], "region")
        self.assertTrue(variable.metadata["default_present"])
        self.assertEqual(variable.metadata["default_value_type"], "string")
        self.assertTrue(variable.metadata["validation_present"])
        self.assertEqual(output.metadata["value_expression_kind"], "traversal_reference")
        self.assertIn(
            ("provider_source", "external:terraform.provider:hashicorp%2Faws"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertIn(
            ("module_source_local", "file:infra/modules/vpc"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertIn(
            ("depends_on", "external:terraform.reference:aws_iam_role.app"),
            {
                (item.metadata["reference_kind"], item.target)
                for item in references
            },
        )
        self.assertNotIn("fake-tfhcl-backend-secret", payload)
        self.assertNotIn("fake-tfhcl-provider-secret", payload)
        self.assertNotIn("fake-tfhcl-module-secret", payload)
        self.assertNotIn("fake-tfhcl-local-secret", payload)
        self.assertNotIn("fake-tfhcl-import-secret", payload)

    def test_terraform_hcl_tfvars_redacts_all_values_by_default(self):
        observations = extract_config_file_observations(
            "prod.auto.tfvars",
            """
region = "us-east-1"
replicas = 3
tags = {
  service = "api"
}
names = ["api", "worker"]
db_password = "fake-tfhcl-tfvars-secret"
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        variables = [item for item in observations if item.kind == "terraform.variable"]

        self.assertEqual(
            {item.metadata["variable_name"] for item in variables},
            {"region", "replicas", "tags", "names", "db_password"},
        )
        self.assertTrue(all(item.metadata["redacted"] for item in variables))
        self.assertEqual(
            {
                (item.metadata["variable_name"], item.metadata["value_type"])
                for item in variables
            },
            {
                ("region", "string"),
                ("replicas", "number"),
                ("tags", "object"),
                ("names", "array"),
                ("db_password", "string"),
            },
        )
        self.assertIn("terraform.redaction", {item.kind for item in observations})
        self.assertNotIn("us-east-1", payload)
        self.assertNotIn("api", payload)
        self.assertNotIn("worker", payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", payload)

    def test_terraform_hcl_parse_errors_and_limits_are_safe(self):
        malformed = extract_config_file_observations(
            "broken.tf",
            'resource "aws_s3_bucket" "broken" {\n  bucket = "fixture"\n',
        )
        limited = extract_config_file_observations(
            "too-many.tf",
            "\n".join(f'variable "v{index}" {{}}' for index in range(260)),
        )

        malformed_errors = [
            item for item in malformed if item.kind == "terraform.parse_error"
        ]
        limited_errors = [
            item for item in limited if item.kind == "terraform.parse_error"
        ]

        self.assertTrue(
            any(
                item.metadata["error_kind"] == "terraform-unclosed-block"
                for item in malformed_errors
            )
        )
        self.assertTrue(
            any(
                item.metadata["error_kind"] == "terraform-block-limit"
                for item in limited_errors
            )
        )

    def test_infrastructure_json_profiles_emit_raw_observations_and_redact_secrets(self):
        cases = [
            (
                "k8s/deployment.json",
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": "app", "namespace": "default"},
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {"name": "app", "image": "example/app:1.0"}
                                ]
                            }
                        }
                    },
                },
                "kubernetes.resource",
            ),
            (
                "argocd/application.json",
                {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    "metadata": {"name": "app"},
                    "spec": {
                        "source": {
                            "repoURL": "https://example.invalid/repo.git",
                            "path": "deploy/app",
                            "targetRevision": "main",
                        },
                        "destination": {"namespace": "default", "server": "https://kubernetes.default.svc"},
                    },
                },
                "argocd.application",
            ),
            (
                "db/changelog.json",
                {
                    "databaseChangeLog": [
                        {
                            "changeSet": {
                                "id": "1",
                                "author": "fixture",
                                "changes": [{"createTable": {"tableName": "example"}}],
                            }
                        }
                    ]
                },
                "liquibase.changelog",
            ),
        ]

        for path, document, expected_kind in cases:
            with self.subTest(path=path):
                observations = extract_config_file_observations(path, json.dumps(document))
                self.assertIn(expected_kind, {item.kind for item in observations})
                self.assertIn("ecosystem.config_profile", {item.kind for item in observations})

        secret_observations = extract_config_file_observations(
            "k8s/secret.json",
            json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "app-secret"},
                    "data": {"password": "fake-k8s-secret-value"},
                }
            ),
        )
        payload = json.dumps(
            [observation.to_dict() for observation in secret_observations],
            sort_keys=True,
        )

        self.assertIn("kubernetes.resource", {item.kind for item in secret_observations})
        self.assertNotIn("fake-k8s-secret-value", payload)

    def test_extracts_json_paths_references_and_redacts_secret_values(self):
        observations = extract_config_file_observations(
            "mcp/repo-map/config.json",
            json.dumps(
                {
                    "projects": {
                        "repo-map": {
                            "root_path": "projects/repo-map",
                            "pg_database": "repomap_repo_map",
                        }
                    },
                    "mcp_servers": {
                        "repomap": {
                            "command": "repomap-kg",
                            "args": ["repomap-kg", "mcp", "serve"],
                            "url": "https://example.com/docs",
                            "env": {
                                "REPOMAP_MCP_CONFIG": "$REPOMAP_MCP_CONFIG",
                                "TOKEN": "secret-value",
                            },
                        }
                    },
                    "api_key": "top-secret",
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        references = [item for item in observations if item.kind == "config.reference"]
        paths = [item for item in observations if item.kind == "config.path"]

        self.assertNotIn("top-secret", payload)
        self.assertNotIn("secret-value", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "json")
        self.assertIn(
            "/projects/repo-map/pg_database",
            {item.metadata["pointer"] for item in paths},
        )
        self.assertIn(
            "/api_key",
            {item.metadata["pointer"] for item in paths},
        )
        api_key = next(item for item in paths if item.metadata["pointer"] == "/api_key")
        self.assertTrue(api_key.metadata["redacted"])
        self.assertEqual(api_key.metadata["redaction_reason"], "secret-prone-key")
        self.assertNotIn("value_summary", api_key.metadata)
        self.assertIn(
            (
                "/projects/repo-map/root_path",
                "file:projects/repo-map",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/command",
                "tool:repomap-kg",
                "tool",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/env/REPOMAP_MCP_CONFIG",
                "env:REPOMAP_MCP_CONFIG",
                "env",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )

    def test_pointer_escaping_and_array_policy_avoid_numeric_identity(self):
        observations = extract_config_file_observations(
            "settings.json",
            json.dumps(
                {
                    "a/b": {"tilde~key": 3},
                    "items": ["one", "two"],
                    "anonymous": [{"command": "do-not-index-by-array-position"}],
                }
            ),
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        array_path = next(item for item in paths if item.metadata["pointer"] == "/items")

        self.assertEqual(json_pointer(("a/b", "tilde~key")), "/a~1b/tilde~0key")
        self.assertIn("/a~1b/tilde~0key", pointers)
        self.assertIn("/items", pointers)
        self.assertEqual(array_path.metadata["value_type"], "array")
        self.assertEqual(array_path.metadata["array_policy"], "summary-only")
        self.assertNotIn("/items/0", pointers)
        self.assertNotIn("/anonymous/0/command", pointers)

    def test_json_parse_error_emits_raw_error_without_document_paths(self):
        observations = extract_config_file_observations(
            "broken.json",
            '{"ok": true,,}',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].confidence, "unknown")
        self.assertEqual(observations[0].metadata["format"], "json")
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-json")

    def test_jsonl_mixed_valid_and_malformed_lines_preserves_valid_records(self):
        observations = extract_config_file_observations(
            "events.jsonl",
            '{"event": "start", "token": "secret-value"}\n'
            "\n"
            '{"event": \n'
            '{"event": "stop", "path": "./logs/out.json"}\n',
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        records = [item for item in observations if item.kind == "config.jsonl_record"]
        errors = [item for item in observations if item.kind == "config.parse_error"]
        references = [item for item in observations if item.kind == "config.reference"]

        self.assertNotIn("secret-value", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "jsonl")
        self.assertEqual([item.metadata["record_index"] for item in records], [0, 1])
        self.assertEqual([item.start_line for item in records], [1, 4])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].metadata["error_kind"], "malformed-jsonl-line")
        self.assertEqual(errors[0].start_line, 3)
        self.assertIn("file:logs/out.json", {item.target for item in references})

    def test_jsonc_comments_and_trailing_commas_are_normalized_conservatively(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            (
                "{\n"
                "  // comment outside a string\n"
                "  \"program\": \"repomap-kg\",\n"
                "  \"nested\": {\n"
                "    \"url\": \"mailto:dev@example.com\", /* block comment */\n"
                "  },\n"
                "}\n"
            ),
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].confidence, "heuristic")
        self.assertIn("tool:repomap-kg", {item.target for item in references})
        self.assertIn("external.url:mailto%3Adev%40example.com", {item.target for item in references})

    def test_jsonc_unterminated_block_comment_emits_parse_error(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "ok": true /* unterminated\n',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].metadata["format"], "jsonc")
        self.assertEqual(
            observations[0].metadata["error_kind"],
            "unsupported-jsonc-construct",
        )

    def test_jsonc_malformed_after_normalization_emits_parse_error(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "ok": }',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-jsonc")
        self.assertEqual(observations[0].metadata["parser"], "jsonc-conservative")

    def test_jsonc_unterminated_string_emits_conservative_parse_error(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "text": "unterminated }',
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(
            observations[0].metadata["error_kind"],
            "unsupported-jsonc-construct",
        )

    def test_jsonc_preserves_comment_markers_inside_strings_and_array_trailing_commas(self):
        observations = extract_config_file_observations(
            "settings.jsonc",
            '{ "text": "not // a comment", "items": [1, 2,], }\n',
        )

        paths = {item.metadata["pointer"]: item for item in observations if item.kind == "config.path"}

        self.assertEqual(paths["/text"].metadata["value_summary"], "not // a comment")
        self.assertEqual(paths["/items"].metadata["value_summaries"], [1, 2])

    def test_absolute_and_parent_relative_file_references_are_conservative(self):
        observations = extract_config_file_observations(
            "configs/settings.json",
            json.dumps(
                {
                    "parent_path": "../README.md",
                    "absolute_path": "/var/db/config.json",
                }
            ),
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertIn("file:README.md", {item.target for item in references})
        self.assertIn(
            "external:file:absolute-config-reference",
            {item.target for item in references},
        )

    def test_jsonl_scalar_record_keeps_safe_summary_without_record_key(self):
        observations = extract_config_file_observations(
            "events.jsonl",
            '"hello"\n42\n',
        )

        records = [item for item in observations if item.kind == "config.jsonl_record"]

        self.assertEqual([item.metadata["value_summary"] for item in records], ["hello", 42])
        self.assertEqual([item.metadata["top_level_type"] for item in records], ["string", "number"])
        self.assertNotIn("config.record", json.dumps([item.to_dict() for item in observations]))

    def test_unknown_command_and_root_scalar_document_are_recorded_honestly(self):
        command_observations = extract_config_file_observations(
            "settings.json",
            '{"command": "bin/tool"}',
        )
        scalar_observations = extract_config_file_observations(
            "value.json",
            "true",
        )

        references = [
            item for item in command_observations if item.kind == "config.reference"
        ]

        self.assertEqual(
            references[0].target,
            "unknown:tool:unknown-config-command",
        )
        self.assertEqual(scalar_observations[0].kind, "config.document")
        self.assertEqual(scalar_observations[0].metadata["top_level_type"], "boolean")

    def test_long_string_summary_and_root_array_document_are_compact(self):
        long_text = "x" * 130
        long_observations = extract_config_file_observations(
            "settings.json",
            json.dumps({"description": long_text}),
        )
        array_observations = extract_config_file_observations(
            "array.json",
            '[{"name": "one"}]',
        )

        description = next(
            item
            for item in long_observations
            if item.kind == "config.path" and item.metadata["pointer"] == "/description"
        )

        self.assertEqual(description.metadata["value_summary"], "<string:130>")
        self.assertEqual(array_observations[0].kind, "config.document")
        self.assertEqual(array_observations[0].metadata["top_level_type"], "array")

    def test_dynamic_and_unknown_references_prefer_placeholders(self):
        observations = extract_config_file_observations(
            "settings.json",
            json.dumps(
                {
                    "outside_path": "../outside.json",
                    "nested_escape_path": "folder/../../outside.json",
                    "dynamic_path": "${HOME}/tool",
                    "command": "echo hello",
                    "env": {"${NAME}": "value"},
                }
            ),
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertIn("unknown:file:repo-escaping-config-reference", {item.target for item in references})
        self.assertEqual(
            sum(
                1
                for item in references
                if item.target == "unknown:file:repo-escaping-config-reference"
            ),
            2,
        )
        self.assertIn("dynamic:file:config-reference-expanded-from-variable", {item.target for item in references})
        self.assertIn("dynamic:tool:config-command-fragment", {item.target for item in references})
        self.assertIn("dynamic:env:dynamic-config-env-name", {item.target for item in references})

    def test_toml_document_paths_references_and_redaction(self):
        observations = extract_config_file_observations(
            "config.toml",
            """
[mcp_servers.repomap]
command = "python3"
args = ["-m", "repomap_kg.mcp_server"]
cwd = "src/main/python"
docs_url = "https://example.com/docs"
api_key = "toml-secret-api-key"
dotted.path.value = "docs/guide.md"

[mcp_servers.repomap.env]
PYTHONPATH = "src/main/python"
TOKEN = "toml-secret-token"

[projects.repo-map]
root_path = "projects/repo-map"
pg_database = "repomap_repo_map"
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("toml-secret-api-key", payload)
        self.assertNotIn("toml-secret-token", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "toml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-tomllib")
        self.assertIn("/mcp_servers/repomap", pointer_by_path)
        self.assertIn("/mcp_servers/repomap/command", pointer_by_path)
        self.assertIn("/mcp_servers/repomap/dotted/path/value", pointer_by_path)
        self.assertIn("/projects/repo-map/root_path", pointer_by_path)
        self.assertTrue(pointer_by_path["/mcp_servers/repomap/api_key"].metadata["redacted"])
        self.assertNotIn(
            "value_summary",
            pointer_by_path["/mcp_servers/repomap/api_key"].metadata,
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/command",
                "tool:python3",
                "tool",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/cwd",
                "file:src/main/python",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/mcp_servers/repomap/env/PYTHONPATH",
                "env:PYTHONPATH",
                "env",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn("env:TOKEN", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )
        self.assertIn("file:docs/guide.md", {item.target for item in references})

    def test_toml_arrays_of_tables_use_stable_member_keys_without_indexes(self):
        observations = extract_config_file_observations(
            "tools.toml",
            """
plugins = ["python", "ruby"]

[[tools]]
name = "repomap"
command = "repomap-kg"
path = "bin/tool"

[[tools]]
id = "helper"
command = "python3"

[[anonymous]]
command = "do-not-index-with-number"
""",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        references = [item for item in observations if item.kind == "config.reference"]
        plugins = next(item for item in paths if item.metadata["pointer"] == "/plugins")
        tools = next(item for item in paths if item.metadata["pointer"] == "/tools")
        anonymous = next(item for item in paths if item.metadata["pointer"] == "/anonymous")

        self.assertEqual(plugins.metadata["array_policy"], "summary-only")
        self.assertEqual(plugins.metadata["value_summaries"], ["python", "ruby"])
        self.assertEqual(tools.metadata["array_policy"], "stable-member-key")
        self.assertEqual(anonymous.metadata["array_policy"], "summary-only")
        self.assertIn("/tools/repomap", pointers)
        self.assertIn("/tools/repomap/command", pointers)
        self.assertIn("/tools/helper/command", pointers)
        self.assertNotIn("/tools/0/command", pointers)
        self.assertNotIn("/anonymous/0/command", pointers)
        self.assertIn("tool:repomap-kg", {item.target for item in references})
        self.assertIn("tool:python3", {item.target for item in references})
        self.assertIn("file:bin/tool", {item.target for item in references})

    def test_toml_malformed_parse_error_is_raw_only(self):
        observations = extract_config_file_observations(
            "bad.toml",
            "[mcp_servers.repomap]\ncommand =\n",
        )

        self.assertEqual([item.kind for item in observations], ["config.parse_error"])
        self.assertEqual(observations[0].confidence, "unknown")
        self.assertEqual(observations[0].metadata["format"], "toml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-tomllib")
        self.assertEqual(observations[0].metadata["error_kind"], "malformed-toml")

    def test_toml_dynamic_and_unknown_references_use_placeholders(self):
        observations = extract_config_file_observations(
            "settings.toml",
            """
outside_path = "../outside.toml"
absolute_path = "/var/db/config.toml"
dynamic_path = "${PROJECT_ROOT}/config.toml"
program = "echo hello"

[env]
"${NAME}" = "value"
""",
        )

        references = [item for item in observations if item.kind == "config.reference"]
        self.assertIn("unknown:file:repo-escaping-config-reference", {item.target for item in references})
        self.assertIn("external:file:absolute-config-reference", {item.target for item in references})
        self.assertIn("dynamic:file:config-reference-expanded-from-variable", {item.target for item in references})
        self.assertIn("dynamic:tool:config-command-fragment", {item.target for item in references})
        self.assertIn("dynamic:env:dynamic-config-env-name", {item.target for item in references})

    def test_yaml_paths_profiles_references_and_redaction(self):
        observations = extract_config_file_observations(
            ".github/workflows/build.yml",
            """
name: Build
on:
  push:
    branches:
      - main
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      API_TOKEN: fake-yaml-secret-token
    steps:
      - id: checkout
        uses: actions/checkout@v4
      - name: Run tests
        run: python3 tools/run_tests.py --suite unit
      - name: Local action
        uses: ./.github/actions/local-action
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("fake-yaml-secret-token", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "yaml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-yaml-conservative")
        self.assertEqual(observations[0].metadata["profile"], "github_actions")
        self.assertEqual(observations[0].metadata["document_count"], 1)
        self.assertIn("/jobs/test/env/API_TOKEN", pointer_by_path)
        self.assertTrue(pointer_by_path["/jobs/test/env/API_TOKEN"].metadata["redacted"])
        self.assertNotIn(
            "value_summary",
            pointer_by_path["/jobs/test/env/API_TOKEN"].metadata,
        )
        self.assertIn("/jobs/test/steps/checkout/uses", pointer_by_path)
        self.assertIn(
            (
                "/jobs/test/steps/checkout/uses",
                "external:github.action:actions%2Fcheckout%40v4",
                "external",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            (
                "/jobs/test/steps/Local action/uses",
                "file:.github/actions/local-action",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )

    def test_yaml_multidocument_profiles_refs_and_secret_redaction(self):
        observations = extract_config_file_observations(
            "k8s/app.yaml",
            """
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  config_path: ./config/app.yml
---
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
stringData:
  password: fake-k8s-secret-password
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  template:
    spec:
      serviceAccountName: app-service
      containers:
        - name: app
          image: example/app:1.0
          envFrom:
            - secretRef:
                name: app-secret
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("fake-k8s-secret-password", payload)
        self.assertEqual(observations[0].metadata["profile"], "kubernetes")
        self.assertEqual(observations[0].metadata["document_count"], 3)
        self.assertIn("/documents/0/kind", pointer_by_path)
        self.assertIn("/documents/1/stringData/password", pointer_by_path)
        self.assertIn(
            "/documents/2/spec/template/spec/containers/app/image",
            pointer_by_path,
        )
        self.assertEqual(
            pointer_by_path["/documents/1/stringData/password"].metadata[
                "redaction_reason"
            ],
            "secret-prone-yaml-path",
        )
        self.assertEqual(
            pointer_by_path[
                "/documents/2/spec/template/spec/containers/app/image"
            ].metadata["stable_member_keys"],
            ["name"],
        )
        self.assertIn(
            (
                "/documents/0/data/config_path",
                "file:k8s/config/app.yml",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertIn(
            "external:docker.image:example%2Fapp%3A1.0",
            {item.target for item in references},
        )

    def test_yaml_custom_tags_anchors_aliases_merge_and_duplicate_keys_are_safe(self):
        tagged = extract_config_file_observations(
            "custom-tags.yaml",
            """
defaults: &defaults
  image: example/base:1.0
service:
  <<: *defaults
  token_ref: !vault fake-vault-secret
  include_file: !include ./values-extra.yml
""",
        )
        duplicate = extract_config_file_observations(
            "duplicate-keys.yaml",
            "service: one\nservice: two\n",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in tagged],
            sort_keys=True,
        )
        paths = [item for item in tagged if item.kind == "config.path"]
        references = [item for item in tagged if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("fake-vault-secret", payload)
        self.assertEqual(observations_format(tagged), "yaml")
        self.assertEqual(pointer_by_path["/defaults"].metadata["anchor"], "defaults")
        self.assertTrue(pointer_by_path["/service/<<"].metadata["merge_key"])
        self.assertEqual(pointer_by_path["/service/<<"].metadata["alias"], "defaults")
        self.assertEqual(
            pointer_by_path["/service/token_ref"].metadata["yaml_tag"],
            "!vault",
        )
        self.assertTrue(pointer_by_path["/service/token_ref"].metadata["redacted"])
        self.assertIn(
            (
                "/service/include_file",
                "file:values-extra.yml",
                "file",
            ),
            {
                (item.metadata["pointer"], item.target, item.metadata["reference_kind"])
                for item in references
            },
        )
        self.assertEqual([item.kind for item in duplicate], ["config.parse_error"])
        self.assertEqual(duplicate[0].metadata["format"], "yaml")
        self.assertEqual(duplicate[0].metadata["error_kind"], "duplicate-yaml-key")
        self.assertEqual(
            duplicate[0].metadata["duplicate_key_policy"],
            "parse-error",
        )

    def test_yaml_profile_detection_matrix_and_openapi_refs(self):
        cases = {
            "Chart.yaml": ("helm_chart", "dependencies:\n  - name: redis\n    repository: https://charts.example.invalid\n"),
            "values.yaml": ("helm_values", "image:\n  repository: example/app\n"),
            "application.yml": ("spring_boot", "spring:\n  config:\n    import: optional:file:./extra.yml\n  datasource:\n    password: fake-spring-secret\n"),
            "openapi.yaml": ("openapi", "openapi: 3.0.0\ninfo:\n  title: API\npaths:\n  /pets:\n    get:\n      responses:\n        '200':\n          $ref: '#/components/responses/Pets'\ncomponents: {}\n"),
            "docker-compose.yml": ("docker_compose", "services:\n  app:\n    image: example/app:latest\n    build:\n      context: ./app\n    env_file: .env\n"),
            ".circleci/config.yml": ("circleci", "version: 2.1\norbs:\n  ruby: circleci/ruby@2.1\njobs:\n  build:\n    docker:\n      - image: cimg/ruby:3.3\n"),
            "grafana/provisioning/datasources.yaml": ("grafana", "apiVersion: 1\ndatasources:\n  - name: main\n    secureJsonData:\n      password: fake-grafana-secret\n"),
            "harness-pipeline.yaml": ("harness", "pipeline:\n  identifier: build\n  projectIdentifier: demo\n  stages: []\n"),
            "serena.yaml": ("serena", "project: repo-map\nserver:\n  token: fake-serena-token\n"),
            "arq-backup-dump.yaml": ("arq_backup", "arq:\n  destination: example-backup\n  arq_encryption_key: fake-arq-key\n"),
            "generic.yaml": ("generic_yaml", "name: generic\n"),
        }

        for path, (profile, content) in cases.items():
            with self.subTest(path=path):
                observations = extract_config_file_observations(path, content)
                payload = json.dumps(
                    [observation.to_dict() for observation in observations],
                    sort_keys=True,
                )
                references = [
                    item for item in observations if item.kind == "config.reference"
                ]

                self.assertEqual(observations[0].metadata["profile"], profile)
                self.assertNotIn("fake-spring-secret", payload)
                self.assertNotIn("fake-grafana-secret", payload)
                self.assertNotIn("fake-serena-token", payload)
                self.assertNotIn("fake-arq-key", payload)
                if path == "openapi.yaml":
                    self.assertIn(
                        "config.path:file%3Aopenapi.yaml:%2Fcomponents%2Fresponses%2FPets",
                        {item.target for item in references},
                    )
                if path == "docker-compose.yml":
                    self.assertIn(
                        "external:docker.image:example%2Fapp%3Alatest",
                        {item.target for item in references},
                    )
                    self.assertIn("file:app", {item.target for item in references})
                    self.assertIn("file:.env", {item.target for item in references})

    def test_openapi3_json_emits_profile_observations_refs_and_redaction(self):
        observations = extract_config_file_observations(
            "contracts/openapi.json",
            json.dumps(
                {
                    "openapi": "3.0.3",
                    "info": {
                        "title": "Example Pets API",
                        "version": "1.0.0",
                        "description": "internal description must not be raw",
                    },
                    "servers": [
                        {"url": "https://user:fake-server-secret@api.example.invalid/v1"}
                    ],
                    "externalDocs": {"url": "https://docs.example.invalid/openapi"},
                    "paths": {
                        "/pets": {
                            "get": {
                                "operationId": "listPets",
                                "tags": ["pets"],
                                "summary": "List all pets",
                                "description": "operation prose must not be raw",
                                "parameters": [
                                    {
                                        "name": "limit",
                                        "in": "query",
                                        "schema": {"type": "integer"},
                                    }
                                ],
                                "responses": {
                                    "200": {
                                        "description": "ok",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": "#/components/schemas/Pet"
                                                }
                                            }
                                        },
                                    },
                                    "400": {
                                        "description": "bad",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": "./schemas/error.yaml#/Error"
                                                }
                                            }
                                        },
                                    },
                                    "422": {
                                        "description": "outside root",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": "../../outside.yaml#/Problem"
                                                }
                                            }
                                        },
                                    },
                                },
                            },
                            "post": {
                                "operationId": "createPet",
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "$ref": "#/components/schemas/PetInput"
                                            },
                                            "example": {
                                                "password": "fake-openapi-password"
                                            },
                                        }
                                    }
                                },
                                "responses": {
                                    "201": {
                                        "description": "created",
                                        "content": {
                                            "application/json": {
                                                "schema": {
                                                    "$ref": (
                                                        "https://api.example.invalid/"
                                                        "schemas/pet.yaml#/Pet"
                                                    )
                                                }
                                            }
                                        },
                                    }
                                },
                            },
                        }
                    },
                    "components": {
                        "schemas": {
                            "Pet": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "token": {
                                        "type": "string",
                                        "example": "fake-openapi-token",
                                    },
                                },
                            },
                            "PetInput": {"type": "object"},
                        },
                        "securitySchemes": {
                            "ApiKeyAuth": {
                                "type": "apiKey",
                                "in": "header",
                                "name": "X-API-Key",
                            }
                        },
                    },
                    "security": [{"ApiKeyAuth": []}],
                }
            ),
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {observation.kind for observation in observations}
        openapi_document = next(
            item for item in observations if item.kind == "openapi.document"
        )
        operation = next(
            item
            for item in observations
            if item.kind == "openapi.operation"
            and item.metadata["operation_id"] == "listPets"
        )
        references = [
            item for item in observations if item.kind == "openapi.reference"
        ]

        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertTrue(
            {
                "openapi.document",
                "openapi.info",
                "openapi.server",
                "openapi.path",
                "openapi.operation",
                "openapi.parameter",
                "openapi.request_body",
                "openapi.response",
                "openapi.schema",
                "openapi.component",
                "openapi.security_scheme",
                "openapi.tag",
                "openapi.reference",
                "openapi.example",
                "openapi.redaction",
            }.issubset(kinds)
        )
        self.assertEqual(openapi_document.metadata["spec_family"], "openapi3")
        self.assertEqual(openapi_document.metadata["spec_version"], "3.0.3")
        self.assertEqual(operation.metadata["method"], "GET")
        self.assertEqual(operation.metadata["path_template"], "/pets")
        self.assertTrue(operation.metadata["description_present"])
        self.assertIn(
            ("internal", "#/components/schemas/Pet", True),
            {
                (
                    item.metadata["reference_scope"],
                    item.metadata["ref_summary"],
                    item.metadata["not_fetched"],
                )
                for item in references
            },
        )
        self.assertIn(
            ("local_file", "./schemas/error.yaml#/Error", True),
            {
                (
                    item.metadata["reference_scope"],
                    item.metadata["ref_summary"],
                    item.metadata["not_fetched"],
                )
                for item in references
            },
        )
        self.assertTrue(
            any(
                item.metadata["reference_scope"] == "remote"
                and item.metadata["not_fetched"]
                for item in references
            )
        )
        self.assertTrue(
            any(
                item.kind == "openapi.parse_error"
                and item.metadata["error_kind"] == "openapi-local-ref-outside-root"
                for item in observations
            )
        )
        self.assertNotIn("fake-openapi-password", payload)
        self.assertNotIn("fake-openapi-token", payload)
        self.assertNotIn("fake-server-secret", payload)
        self.assertNotIn("../../outside.yaml#/Problem", payload)
        self.assertNotIn("internal description must not be raw", payload)
        self.assertNotIn("operation prose must not be raw", payload)

    def test_openapi_yaml_and_swagger2_emit_profile_observations(self):
        openapi_yaml = extract_config_file_observations(
            "service.openapi.yaml",
            """
openapi: 3.1.0
info:
  title: YAML API
  version: "2026.07"
paths:
  /health:
    get:
      operationId: healthCheck
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Health"
components:
  schemas:
    Health:
      type: object
      properties:
        status:
          type: string
""",
        )
        swagger_json = extract_config_file_observations(
            "swagger.json",
            json.dumps(
                {
                    "swagger": "2.0",
                    "info": {"title": "Swagger API", "version": "2.0"},
                    "host": "api.example.invalid",
                    "basePath": "/v2",
                    "schemes": ["https"],
                    "paths": {
                        "/widgets": {
                            "get": {
                                "operationId": "listWidgets",
                                "responses": {
                                    "200": {
                                        "description": "ok",
                                        "schema": {"$ref": "#/definitions/Widget"},
                                    }
                                },
                            }
                        }
                    },
                    "definitions": {"Widget": {"type": "object"}},
                    "securityDefinitions": {
                        "CookieAuth": {
                            "type": "apiKey",
                            "in": "header",
                            "name": "Cookie",
                        }
                    },
                }
            ),
        )

        yaml_kinds = {item.kind for item in openapi_yaml}
        swagger_kinds = {item.kind for item in swagger_json}
        yaml_document = next(
            item for item in openapi_yaml if item.kind == "openapi.document"
        )
        swagger_document = next(
            item for item in swagger_json if item.kind == "openapi.document"
        )
        swagger_response = next(
            item for item in swagger_json if item.kind == "openapi.response"
        )

        self.assertIn("config.document", yaml_kinds)
        self.assertIn("config.path", yaml_kinds)
        self.assertIn("openapi.document", yaml_kinds)
        self.assertIn("openapi.operation", yaml_kinds)
        self.assertIn("openapi.schema", yaml_kinds)
        self.assertEqual(yaml_document.metadata["format"], "yaml")
        self.assertEqual(yaml_document.metadata["spec_family"], "openapi3")
        self.assertEqual(yaml_document.metadata["spec_version"], "3.1.0")
        self.assertIn("openapi.document", swagger_kinds)
        self.assertIn("openapi.security_scheme", swagger_kinds)
        self.assertEqual(swagger_document.metadata["spec_family"], "swagger2")
        self.assertEqual(swagger_document.metadata["spec_version"], "2.0")
        self.assertEqual(swagger_response.metadata["status_code"], "200")
        self.assertEqual(swagger_response.metadata["media_types"], [])

    def test_openapi_parse_errors_limits_and_unsupported_specs_are_profile_raw(self):
        malformed_json = extract_config_file_observations(
            "openapi.json",
            '{"openapi": "3.0.0", "paths": ',
        )
        unsupported = extract_config_file_observations(
            "openapi.json",
            json.dumps({"openapi": "1.2.3", "info": {}, "paths": {}}),
        )
        too_many_paths = extract_config_file_observations(
            "openapi.json",
            json.dumps(
                {
                    "openapi": "3.0.0",
                    "info": {"title": "Too Many", "version": "1.0"},
                    "paths": {
                        f"/item-{index}": {
                            "get": {"responses": {"200": {"description": "ok"}}}
                        }
                        for index in range(130)
                    },
                }
            ),
        )

        self.assertIn("config.parse_error", {item.kind for item in malformed_json})
        self.assertIn("openapi.parse_error", {item.kind for item in malformed_json})
        self.assertIn("config.document", {item.kind for item in unsupported})
        self.assertIn("openapi.parse_error", {item.kind for item in unsupported})
        self.assertTrue(
            any(
                item.metadata["error_kind"] == "unsupported-openapi-version"
                for item in unsupported
                if item.kind == "openapi.parse_error"
            )
        )
        self.assertTrue(
            any(
                item.kind == "openapi.parse_error"
                and item.metadata["error_kind"] == "openapi-path-limit"
                for item in too_many_paths
            )
        )

    def test_yaml_malformed_and_limit_errors_are_raw_only(self):
        malformed = extract_config_file_observations("bad.yaml", "name: [unterminated\n")
        too_large_scalar = extract_config_file_observations(
            "long.yaml",
            "description: " + ("x" * 5000) + "\n",
        )

        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(malformed[0].metadata["format"], "yaml")
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-yaml")
        self.assertEqual([item.kind for item in too_large_scalar], ["config.parse_error"])
        self.assertEqual(
            too_large_scalar[0].metadata["error_kind"],
            "yaml-scalar-length-limit",
        )

    def test_plist_document_paths_references_and_redaction(self):
        observations = extract_config_file_observations(
            "chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>HomepageLocation</key>
    <string>https://example.com/home</string>
    <key>PolicyPath</key>
    <string>./managed/policy.json</string>
    <key>Environment</key>
    <dict>
      <key>CHROME_POLICY_HOME</key>
      <string>$CHROME_POLICY_HOME</string>
    </dict>
    <key>api_key</key>
    <string>plist-secret-value</string>
  </dict>
</plist>
""",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}

        self.assertNotIn("plist-secret-value", payload)
        self.assertEqual(observations[0].kind, "config.document")
        self.assertEqual(observations[0].metadata["format"], "plist-xml")
        self.assertEqual(observations[0].metadata["parser"], "stdlib-elementtree-safe")
        self.assertEqual(observations[0].metadata["document_role"], "chrome-policy")
        self.assertEqual(
            observations[0].metadata["safety_mode"],
            "pre-scan-no-doctype-entity-no-external-resources",
        )
        self.assertIn("/HomepageLocation", pointer_by_path)
        self.assertIn("/Environment/CHROME_POLICY_HOME", pointer_by_path)
        self.assertTrue(pointer_by_path["/api_key"].metadata["redacted"])
        self.assertNotIn("value_summary", pointer_by_path["/api_key"].metadata)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fhome",
            {item.target for item in references},
        )
        self.assertIn("file:managed/policy.json", {item.target for item in references})
        self.assertIn("env:CHROME_POLICY_HOME", {item.target for item in references})

    def test_plist_arrays_use_summary_or_stable_member_identity_without_indexes(self):
        observations = extract_config_file_observations(
            "policies/chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>ExtensionInstallForcelist</key>
    <array>
      <string>abcdefghijklmnopabcdefghijklmnop;https://example.com/update.xml</string>
    </array>
    <key>ManagedBookmarks</key>
    <array>
      <dict>
        <key>name</key>
        <string>Docs</string>
        <key>url</key>
        <string>https://example.com/docs</string>
      </dict>
      <dict>
        <key>id</key>
        <string>LocalHelp</string>
        <key>path</key>
        <string>../docs/help.html</string>
      </dict>
    </array>
    <key>AnonymousRules</key>
    <array>
      <dict>
        <key>url</key>
        <string>https://example.com/anonymous</string>
      </dict>
    </array>
  </dict>
</plist>
""",
        )

        paths = [item for item in observations if item.kind == "config.path"]
        pointers = {item.metadata["pointer"] for item in paths}
        references = [item for item in observations if item.kind == "config.reference"]
        install_list = next(
            item for item in paths if item.metadata["pointer"] == "/ExtensionInstallForcelist"
        )
        bookmarks = next(
            item for item in paths if item.metadata["pointer"] == "/ManagedBookmarks"
        )
        anonymous = next(
            item for item in paths if item.metadata["pointer"] == "/AnonymousRules"
        )

        self.assertEqual(install_list.metadata["array_policy"], "summary-only")
        self.assertEqual(bookmarks.metadata["array_policy"], "stable-member-key")
        self.assertEqual(anonymous.metadata["array_policy"], "summary-only")
        self.assertIn("/ManagedBookmarks/Docs/url", pointers)
        self.assertIn("/ManagedBookmarks/LocalHelp/path", pointers)
        self.assertNotIn("/ManagedBookmarks/0/url", pointers)
        self.assertNotIn("/AnonymousRules/0/url", pointers)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )
        self.assertIn("file:docs/help.html", {item.target for item in references})

    def test_plist_reference_placeholders_are_conservative(self):
        observations = extract_config_file_observations(
            "policies/chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>OutsidePath</key>
    <string>../../outside.json</string>
    <key>AbsolutePath</key>
    <string>/Library/Managed Preferences/com.google.Chrome.plist</string>
    <key>DynamicPath</key>
    <string>${POLICY_DIR}/chrome.json</string>
  </dict>
</plist>
""",
        )

        references = [item for item in observations if item.kind == "config.reference"]

        self.assertIn(
            "unknown:file:repo-escaping-config-reference",
            {item.target for item in references},
        )
        self.assertIn(
            "external:file:absolute-config-reference",
            {item.target for item in references},
        )
        self.assertIn(
            "dynamic:file:config-reference-expanded-from-variable",
            {item.target for item in references},
        )

    def test_plist_malformed_and_unsafe_xml_emit_parse_errors(self):
        malformed = extract_config_file_observations(
            "bad.plist",
            "<plist><dict><key>MissingValue</key></dict></plist>",
        )
        unsafe = extract_config_file_observations(
            "dangerous.plist",
            """<?xml version="1.0"?>
<!DOCTYPE plist [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<plist><dict><key>Bad</key><string>&xxe;</string></dict></plist>
""",
        )
        processing_instruction = extract_config_file_observations(
            "stylesheet.plist",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<plist><dict/></plist>
""",
        )

        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(
            malformed[0].metadata["error_kind"],
            "unsupported-plist-shape",
        )
        self.assertEqual([item.kind for item in unsafe], ["config.parse_error"])
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")
        self.assertNotIn("file:///etc/passwd", unsafe[0].metadata["message_summary"])
        self.assertEqual(
            processing_instruction[0].metadata["error_kind"],
            "unsafe-xml-construct",
        )

    def test_generic_xml_extracts_spring_structure_references_and_redacts(self):
        observations = extract_config_file_observations(
            "src/main/resources/applicationContext.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans https://www.springframework.org/schema/beans/spring-beans.xsd">
  <bean id="service" class="com.example.Service">
    <property name="configPath" value="./config/service.properties"/>
    <property name="jdbcUrl" value="${db.url}"/>
    <property name="DB_PASSWORD" value="${env.DB_PASSWORD}"/>
    <property name="api_key" value="spring-secret-value"/>
    <constructor-arg ref="repository"/>
  </bean>
  <bean id="repository" class="com.example.Repository"/>
</beans>
""",
        )
        plist_xml = extract_config_file_observations(
            "policies/chrome-policy.xml",
            "<plist><dict><key>HomepageLocation</key><string>https://example.com</string></dict></plist>",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = [item.kind for item in observations]
        document = observations[0]
        elements = [item for item in observations if item.kind == "xml.element"]
        attributes = [item for item in observations if item.kind == "xml.attribute"]
        references = [item for item in observations if item.kind == "xml.reference"]
        element_by_pointer = {item.metadata["xml_pointer"]: item for item in elements}
        attr_by_pointer_name = {
            (item.metadata["element_pointer"], item.metadata["attribute_name"]): item
            for item in attributes
        }

        self.assertNotIn("spring-secret-value", payload)
        self.assertEqual(document.kind, "xml.document")
        self.assertEqual(document.metadata["format"], "xml")
        self.assertEqual(document.metadata["document_role"], "spring-config")
        self.assertEqual(document.metadata["root_local_name"], "beans")
        self.assertIn("xml.document", kinds)
        self.assertIn("xml.element", kinds)
        self.assertIn("xml.attribute", kinds)
        self.assertIn("xml.reference", kinds)
        self.assertIn("/beans/bean", element_by_pointer)
        self.assertIn("/beans/bean[2]", element_by_pointer)
        self.assertEqual(
            element_by_pointer["/beans/bean"].metadata["role_hint"],
            "spring-bean",
        )
        self.assertEqual(element_by_pointer["/beans/bean"].metadata["bean_id"], "service")
        self.assertEqual(
            element_by_pointer["/beans/bean"].metadata["class_name"],
            "com.example.Service",
        )
        self.assertEqual(
            attr_by_pointer_name[("/beans/bean/property[4]", "value")].metadata[
                "redacted"
            ],
            True,
        )
        self.assertNotIn(
            "value_summary",
            attr_by_pointer_name[("/beans/bean/property[4]", "value")].metadata,
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fwww.springframework.org%2Fschema%2Fbeans%2Fspring-beans.xsd",
            {item.target for item in references},
        )
        self.assertIn("file:src/main/resources/config/service.properties", {item.target for item in references})
        self.assertIn("env:DB_PASSWORD", {item.target for item in references})
        self.assertIn("dynamic:xml.property-placeholder:spring-maven-property", {item.target for item in references})
        self.assertEqual(plist_xml[0].kind, "config.document")
        self.assertEqual(plist_xml[0].metadata["format"], "plist-xml")

    def test_generic_xml_extracts_maven_metadata_and_safety_errors(self):
        pom_observations = extract_config_file_observations(
            "pom.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>${revision}</version>
  <properties>
    <revision>1.0.0</revision>
    <api.token>maven-secret-value</api.token>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-context</artifactId>
      <version>${spring.version}</version>
    </dependency>
  </dependencies>
</project>
""",
        )
        unsafe = extract_config_file_observations(
            "src/main/resources/bad-dangerous.xml",
            """<?xml version="1.0"?>
<!DOCTYPE beans [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<beans><bean id="bad">&xxe;</bean></beans>
""",
        )
        malformed = extract_config_file_observations(
            "src/main/resources/bad.xml",
            "<beans><bean></beans>",
        )

        payload = json.dumps(
            [observation.to_dict() for observation in pom_observations],
            sort_keys=True,
        )
        document = pom_observations[0]
        elements = [item for item in pom_observations if item.kind == "xml.element"]
        references = [item for item in pom_observations if item.kind == "xml.reference"]
        dependency = next(
            item
            for item in elements
            if item.metadata["xml_pointer"] == "/project/dependencies/dependency"
        )

        self.assertNotIn("maven-secret-value", payload)
        self.assertEqual(document.metadata["document_role"], "maven-pom")
        self.assertEqual(dependency.metadata["role_hint"], "maven-dependency")
        self.assertEqual(dependency.metadata["maven_group_id"], "org.springframework")
        self.assertEqual(dependency.metadata["maven_artifact_id"], "spring-context")
        self.assertEqual(dependency.metadata["maven_version"], "${spring.version}")
        self.assertIn(
            "external.url:https%3A%2F%2Fmaven.apache.org%2Fxsd%2Fmaven-4.0.0.xsd",
            {item.target for item in references},
        )
        self.assertIn(
            "dynamic:xml.property-placeholder:spring-maven-property",
            {item.target for item in references},
        )
        self.assertEqual([item.kind for item in unsafe], ["xml.parse_error"])
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")
        self.assertNotIn("file:///etc/passwd", unsafe[0].metadata["message_summary"])
        self.assertEqual([item.kind for item in malformed], ["xml.parse_error"])
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-xml")

    def test_generic_xml_classifies_conservative_reference_targets(self):
        observations = extract_config_file_observations(
            "src/main/resources/paths.xml",
            """<?xml version="1.0"?>
<settings>
  <path value="../../../../outside.properties"/>
  <path value="/Library/Application Support/config.xml"/>
  <path value="${CONFIG_DIR}/app.xml"/>
  <path value="~/Library/config.xml"/>
  <path value="*.xml"/>
  <url>mailto:dev@example.com</url>
  <env>${env.SERVICE_TOKEN}</env>
</settings>
""",
        )

        references = [item for item in observations if item.kind == "xml.reference"]
        targets = {item.target for item in references}
        reference_by_target = {item.target: item for item in references}

        self.assertIn("unknown:file:repo-escaping-xml-reference", targets)
        self.assertIn("external:file:absolute-xml-reference", targets)
        self.assertIn("dynamic:file:xml-reference-expanded-from-variable", targets)
        self.assertIn(
            "external.url:mailto%3Adev%40example.com",
            targets,
        )
        self.assertIn("env:SERVICE_TOKEN", targets)
        self.assertEqual(
            reference_by_target[
                "unknown:file:repo-escaping-xml-reference"
            ].metadata["reference_kind"],
            "unknown",
        )

    def test_generic_xml_processing_instruction_is_safety_error(self):
        observations = extract_config_file_observations(
            "src/main/resources/stylesheet.xml",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<beans/>
""",
        )

        self.assertEqual([item.kind for item in observations], ["xml.parse_error"])
        self.assertEqual(
            observations[0].metadata["error_kind"],
            "unsafe-xml-construct",
        )
        self.assertNotIn("https://example.com/style.xsl", observations[0].metadata)


if __name__ == "__main__":
    unittest.main()
