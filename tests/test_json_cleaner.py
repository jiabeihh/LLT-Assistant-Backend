"""Tests for JSON cleaning utilities."""

import pytest
from app.utils.json_cleaner import JSONCleaner, clean_llm_json, parse_llm_json


@pytest.fixture
def cleaner():
    """JSONCleaner instance for testing."""
    return JSONCleaner()


class TestJSONCleaner:
    """Test cases for JSONCleaner class."""

    def test_clean_markdown_code_block(self, cleaner):
        """Test cleaning JSON from Markdown code blocks."""
        response = '''Here's the JSON response:

```json
{
    "status": "success",
    "data": [1, 2, 3]
}
```

This should work!'''

        result = cleaner.clean_json_response(response)
        expected = '{\n    "status": "success",\n    "data": [1, 2, 3]\n}'
        assert result == expected

    def test_clean_with_prefixes(self, cleaner):
        """Test removing common LLM prefixes."""
        response = 'Here is the JSON: {"result": "valid", "count": 5}'

        result = cleaner.clean_json_response(response)
        expected = '{"result": "valid", "count": 5}'
        assert result == expected

    def test_clean_with_suffixes(self, cleaner):
        """Test removing common LLM suffixes."""
        response = '{"status": "ok"}\n\nThis is the result you requested.'

        result = cleaner.clean_json_response(response)
        expected = '{"status": "ok"}'
        assert result == expected

    def test_fix_trailing_commas(self, cleaner):
        """Test fixing trailing commas in JSON."""
        response = '{"items": [1, 2, 3,], "nested": {"a": 1,}}'

        result = cleaner.clean_json_response(response)
        expected = '{"items": [1, 2, 3], "nested": {"a": 1}}'
        assert result == expected

    def test_clean_single_quotes(self, cleaner):
        """Test fixing single quotes in JSON."""
        response = "{'name': 'test', 'value': 'data'}"

        result = cleaner.try_clean_and_parse(response)
        assert result == {"name": "test", "value": "data"}

    def test_already_valid_json(self, cleaner):
        """Test that already valid JSON is preserved."""
        response = '{"valid": true, "number": 42}'

        result = cleaner.clean_json_response(response)
        assert result == response

    def test_empty_response(self, cleaner):
        """Test handling empty response."""
        with pytest.raises(ValueError, match="Empty response provided"):
            cleaner.clean_json_response("")

    def test_invalid_json_after_cleaning(self, cleaner):
        """Test error when JSON is invalid after cleaning."""
        response = "This is not JSON at all"

        with pytest.raises(ValueError, match="not valid JSON"):
            cleaner.clean_json_response(response)

    def test_complex_nested_json(self, cleaner):
        """Test cleaning complex nested JSON structures."""
        response = '''Here's your response:

```json
{
    "users": [
        {
            "id": 1,
            "name": "Alice",
            "active": true,
            "roles": ["admin", "user"]
        },
        {
            "id": 2,
            "name": "Bob",
            "active": false,
            "roles": ["user"]
        }
    ],
    "metadata": {
        "total": 2,
        "page": 1,
        "hasMore": false,
    }
}
```

Enjoy!'''

        result = cleaner.clean_json_response(response)
        # Should be valid JSON
        import json
        parsed = json.loads(result)
        assert len(parsed["users"]) == 2
        assert parsed["metadata"]["total"] == 2

    def test_try_clean_and_parse_success(self, cleaner):
        """Test successful cleaning and parsing."""
        response = 'Result: {"success": true, "data": [1, 2, 3]}'

        result = cleaner.try_clean_and_parse(response)
        assert result == {"success": True, "data": [1, 2, 3]}

    def test_try_clean_and_parse_failure(self, cleaner):
        """Test failure when JSON cannot be parsed."""
        response = "This is completely invalid JSON"

        with pytest.raises(ValueError, match="Failed to parse JSON"):
            cleaner.try_clean_and_parse(response)

    def test_aggressive_cleaning(self, cleaner):
        """Test aggressive cleaning for difficult cases."""
        response = '''Some text before
        {
            "keep": "this",
            "data": [1, 2, 3]
        }
        Some text after'''

        result = cleaner._aggressive_cleaning(response)
        expected = '{\n            "keep": "this",\n            "data": [1, 2, 3]\n        }'
        assert result == expected


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_clean_llm_json_function(self):
        """Test clean_llm_json convenience function."""
        response = '```json\n{"test": "value"}\n```'
        result = clean_llm_json(response)
        expected = '{"test": "value"}'
        assert result == expected

    def test_parse_llm_json_function(self):
        """Test parse_llm_json convenience function."""
        response = 'Response: {"parsed": true, "number": 42}'
        result = parse_llm_json(response)
        assert result == {"parsed": True, "number": 42}

    def test_parse_llm_json_function_with_markdown(self):
        """Test parse_llm_json with Markdown formatting."""
        response = '''Here's the result:

```json
{
    "status": "success",
    "items": ["a", "b", "c"]
}
```
'''

        result = parse_llm_json(response)
        assert result == {"status": "success", "items": ["a", "b", "c"]}


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_json_with_newlines_and_tabs(self, cleaner):
        """Test JSON containing newlines and tabs."""
        response = '''{"text": "Line 1\\nLine 2", "tab": "Col1\\tCol2"}'''

        result = cleaner.try_clean_and_parse(response)
        assert result["text"] == "Line 1\nLine 2"
        assert result["tab"] == "Col1\tCol2"

    def test_json_with_escaped_quotes(self, cleaner):
        """Test JSON with escaped quotes."""
        response = r'{"message": "He said \"Hello\""}'

        result = cleaner.try_clean_and_parse(response)
        assert result["message"] == 'He said "Hello"'

    def test_json_with_unicode(self, cleaner):
        """Test JSON with Unicode characters."""
        response = '{"emoji": "😀", "chinese": "你好", "math": "∑"}'

        result = cleaner.try_clean_and_parse(response)
        assert result["emoji"] == "😀"
        assert result["chinese"] == "你好"
        assert result["math"] == "∑"

    def test_malformed_brackets(self, cleaner):
        """Test JSON with malformed brackets."""
        response = '{"data": [1, 2, 3}'  # Missing closing bracket

        with pytest.raises(ValueError):
            cleaner.clean_json_response(response)

    def test_nested_arrays_and_objects(self, cleaner):
        """Test deeply nested JSON structures."""
        response = '''```json
        {
            "level1": {
                "level2": {
                    "level3": {
                        "array": [
                            {"nested": "value1"},
                            {"nested": "value2"}
                        ]
                    }
                }
            }
        }
        ```'''

        result = cleaner.try_clean_and_parse(response)
        assert result["level1"]["level2"]["level3"]["array"][0]["nested"] == "value1"
        assert result["level1"]["level2"]["level3"]["array"][1]["nested"] == "value2"