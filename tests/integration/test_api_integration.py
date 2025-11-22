"""
Integration tests for API endpoints and end-to-end workflows.

Tests cover complete request-response cycles, real analysis workflows,
and integration between components.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def integration_client():
    """Provide test client for integration tests."""
    return TestClient(app)


class TestRootEndpoint:
    """Integration tests for root endpoint."""

    def test_root_endpoint(self, integration_client):
        """Test root endpoint returns service information."""
        response = integration_client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["name"] == "LLT Assistant Backend"


class TestQualityAnalysisEndpoint:
    """Integration tests for quality analysis endpoint."""

    def test_quality_analyze_simple_test(self, integration_client):
        """Test analyzing a simple test file."""
        payload = {
            "files": [
                {
                    "path": "test_example.py",
                    "content": """
def test_addition():
    result = 1 + 1
    assert result == 2
""",
                }
            ],
            "mode": "fast",  # Use fast mode (rules-only)
        }

        response = integration_client.post("/quality/analyze", json=payload)

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "analysis_id" in data
        assert "summary" in data
        assert "issues" in data

        # Verify summary
        summary = data["summary"]
        assert "total_files" in summary
        assert "total_issues" in summary
        assert "critical_issues" in summary
        assert summary["total_files"] == 1
        assert isinstance(summary["total_issues"], int)

    def test_quality_analyze_test_with_issues(self, integration_client):
        """Test analyzing a test file with quality issues."""
        payload = {
            "files": [
                {
                    "path": "test_bad.py",
                    "content": """
def test_redundant():
    value = 42
    assert value == 42
    assert value == 42  # Redundant assertion
""",
                }
            ],
            "mode": "fast",
        }

        response = integration_client.post("/quality/analyze", json=payload)

        assert response.status_code == 200
        data = response.json()

        # Verify response structure is correct
        assert "summary" in data
        assert "issues" in data
        assert isinstance(data["issues"], list)

        # If issues detected, verify structure
        if len(data["issues"]) > 0:
            issue = data["issues"][0]
            assert "file_path" in issue
            assert "line" in issue
            assert "severity" in issue
            assert "code" in issue
            assert "message" in issue
            assert "detected_by" in issue

    def test_quality_analyze_multiple_files(self, integration_client):
        """Test analyzing multiple test files."""
        payload = {
            "files": [
                {"path": "test_one.py", "content": "def test_one(): assert True"},
                {"path": "test_two.py", "content": "def test_two(): assert 1 == 1"},
                {
                    "path": "test_three.py",
                    "content": "def test_three(): assert 2 + 2 == 4",
                },
            ],
            "mode": "fast",
        }

        response = integration_client.post("/quality/analyze", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert data["summary"]["total_files"] == 3


class TestImpactAnalysisEndpoint:
    """Integration tests for impact analysis endpoint."""

    def test_analyze_impact_simple(self, integration_client):
        """Test impact analysis with basic project context."""
        payload = {
            "project_context": {
                "files_changed": [{"path": "src/module.py", "change_type": "modified"}],
                "related_tests": ["tests/test_module.py"],
            }
        }

        response = integration_client.post("/analysis/impact", json=payload)

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "impacted_tests" in data
        assert "severity" in data
        assert "suggested_action" in data

        # Verify impacted_tests is a list
        assert isinstance(data["impacted_tests"], list)

    def test_analyze_impact_no_files_changed_returns_error(self, integration_client):
        """Test impact analysis fails when files_changed is empty."""
        payload = {
            "project_context": {
                "files_changed": [],  # Empty
                "related_tests": ["tests/test_module.py"],
            }
        }

        response = integration_client.post("/analysis/impact", json=payload)

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data


class TestWorkflowsEndpoints:
    """Integration tests for workflow endpoints."""

    def test_workflows_generate_tests_submit(self, integration_client):
        """Test submitting test generation workflow."""
        payload = {
            "source_code": """
def add(a, b):
    return a + b
""",
            "user_description": "Test that add function works correctly",
            "existing_test_code": None,
            "context": None,
        }

        response = integration_client.post("/workflows/generate-tests", json=payload)

        assert response.status_code == 202  # Accepted
        data = response.json()
        assert "task_id" in data
        assert "status" in data
        assert data["status"] == "pending"

    def test_optimization_coverage_submit(self, integration_client):
        """Test submitting coverage optimization."""
        payload = {
            "source_code": """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
""",
            "existing_test_code": """
def test_add():
    assert add(1, 1) == 2
""",
            "uncovered_ranges": [{"start_line": 5, "end_line": 7, "type": "line"}],
            "framework": "pytest",
        }

        response = integration_client.post("/optimization/coverage", json=payload)

        assert response.status_code == 202  # Accepted
        data = response.json()
        assert "task_id" in data

    def test_tasks_status_check(self, integration_client):
        """Test checking task status."""
        # First create a task
        payload = {
            "source_code": """
def add(a, b):
    return a + b
""",
            "user_description": "Test adding two numbers",
        }
        create_response = integration_client.post(
            "/workflows/generate-tests", json=payload
        )
        task_id = create_response.json()["task_id"]

        # Then check its status
        response = integration_client.get(f"/tasks/{task_id}")

        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert "status" in data


class TestErrorHandling:
    """Integration tests for error handling."""

    def test_404_on_invalid_endpoint(self, integration_client):
        """Test that invalid endpoints return 404."""
        response = integration_client.get("/nonexistent")

        assert response.status_code == 404

    def test_405_on_wrong_method(self, integration_client):
        """Test that wrong HTTP method returns 405."""
        # Test POST endpoint with GET
        response = integration_client.get("/quality/analyze")
        assert response.status_code == 405

    def test_malformed_json_returns_error(self, integration_client):
        """Test that malformed JSON returns error."""
        response = integration_client.post(
            "/quality/analyze",
            data="this is not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code in [400, 422]


class TestPerformance:
    """Integration tests for performance characteristics."""

    @pytest.mark.slow
    def test_quality_analyze_large_file(self, integration_client):
        """Test analyzing a large test file."""
        # Generate large test content
        test_functions = "\n\n".join(
            [
                f"""def test_function_{i}():
    result = {i} + {i}
    assert result == {i * 2}"""
                for i in range(50)
            ]
        )

        payload = {
            "files": [{"path": "test_large.py", "content": test_functions}],
            "mode": "fast",
        }

        response = integration_client.post("/quality/analyze", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert data["summary"]["total_files"] == 1

    @pytest.mark.slow
    def test_quality_analyze_many_files(self, integration_client):
        """Test analyzing many small test files."""
        files = [
            {"path": f"test_{i}.py", "content": f"def test_{i}(): assert {i} == {i}"}
            for i in range(20)
        ]

        payload = {"files": files, "mode": "fast"}

        response = integration_client.post("/quality/analyze", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_files"] == 20


class TestCorsAndOpenAPI:
    """Integration tests for CORS and OpenAPI."""

    def test_openapi_json_available(self, integration_client):
        """Test OpenAPI JSON is available."""
        response = integration_client.get("/openapi.json")
        assert response.status_code == 200

    def test_swagger_ui_available(self, integration_client):
        """Test Swagger UI is available."""
        response = integration_client.get("/docs")
        assert response.status_code == 200

    def test_redoc_available(self, integration_client):
        """Test ReDoc is available."""
        response = integration_client.get("/redoc")
        assert response.status_code == 200
