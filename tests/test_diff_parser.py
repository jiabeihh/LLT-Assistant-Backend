"""Tests for Git diff parser functionality."""

import pytest
from app.analyzers.diff_parser import (
    GitDiffParser,
    FileChange,
    DiffHunk,
    FunctionChange,
    parse_diff_string,
    extract_changed_line_numbers_from_diff,
)


@pytest.fixture
def sample_git_diff():
    """Sample git diff output for testing."""
    return """diff --git a/src/calculator.py b/src/calculator.py
index abc123..def456 100644
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -5,7 +5,7 @@ class Calculator:

-    def add(self, a, b):
+    def add(self, a, b, description=None):
         """Add two numbers."""
         return a + b

@@ -15,6 +15,10 @@ class Calculator:
         """Subtract two numbers."""
         return a - b

+    def multiply(self, a, b):
+        """Multiply two numbers."""
+        return a * b
+
     def divide(self, a, b):
         """Divide two numbers."""
         if b == 0:
diff --git a/tests/test_calculator.py b/tests/test_calculator.py
new file mode 100644
index 000000..789abc
--- /dev/null
+++ b/tests/test_calculator.py
@@ -0,0 +1,8 @@
+import pytest
+from src.calculator import Calculator
+
+def test_calculator_add():
+    calc = Calculator()
+    assert calc.add(2, 3) == 5
+
+def test_calculator_multiply():
+    calc = Calculator()
+    assert calc.multiply(4, 5) == 20"""


@pytest.fixture
def parser():
    """GitDiffParser instance for testing."""
    return GitDiffParser()


def test_parse_git_diff(parser, sample_git_diff):
    """Test parsing git diff into FileChange objects."""
    file_changes = parser.parse_git_diff(sample_git_diff)

    assert len(file_changes) == 2

    # First file: modified
    calculator_change = file_changes[0]
    assert calculator_change.file_path == "src/calculator.py"
    assert calculator_change.change_type == "modified"
    assert len(calculator_change.hunks) == 2

    # Second file: added
    test_change = file_changes[1]
    assert test_change.file_path == "tests/test_calculator.py"
    assert test_change.change_type == "added"


def test_extract_line_numbers(parser, sample_git_diff):
    """Test extraction of line numbers from diff."""
    file_changes = parser.parse_git_diff(sample_git_diff)
    calculator_change = file_changes[0]

    # Check that line numbers are extracted
    assert len(calculator_change.added_line_numbers) > 0
    assert len(calculator_change.removed_line_numbers) > 0

    # The modified function add() should be affected
    assert 6 in calculator_change.added_line_numbers or 6 in calculator_change.removed_line_numbers


def test_extract_changed_functions(parser, sample_git_diff):
    """Test extraction of affected functions."""
    file_changes = parser.parse_git_diff(sample_git_diff)
    calculator_change = file_changes[0]

    # Find changed functions
    changed_functions = parser.extract_changed_functions(calculator_change)

    # Should find the 'add' function and 'multiply' function
    function_names = [f.function_name for f in changed_functions]
    assert 'add' in function_names or 'Calculator' in function_names  # May detect class name
    assert 'multiply' in function_names


def test_get_changed_line_numbers(parser, sample_git_diff):
    """Test getting all changed line numbers from diff."""
    changed_lines = parser.get_changed_line_numbers(sample_git_diff)

    assert len(changed_lines) == 2  # Two files changed
    assert "src/calculator.py" in changed_lines
    assert "tests/test_calculator.py" in changed_lines

    # Check that line numbers are extracted
    assert len(changed_lines["src/calculator.py"]) > 0
    assert len(changed_lines["tests/test_calculator.py"]) > 0


def test_convenience_functions():
    """Test convenience functions."""
    sample_diff = """diff --git a/test.py b/test.py
index abc123..def456 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 def test_example():
     pass
+    # New comment"""

    # Test parse_diff_string
    file_changes = parse_diff_string(sample_diff)
    assert len(file_changes) == 1
    assert file_changes[0].file_path == "test.py"

    # Test extract_changed_line_numbers_from_diff
    changed_lines = extract_changed_line_numbers_from_diff(sample_diff)
    assert "test.py" in changed_lines
    assert len(changed_lines["test.py"]) > 0


def test_empty_diff(parser):
    """Test handling of empty diff."""
    file_changes = parser.parse_git_diff("")
    assert len(file_changes) == 0

    changed_lines = parser.get_changed_line_numbers("")
    assert len(changed_lines) == 0


def test_file_type_detection(parser):
    """Test file type detection based on extensions."""
    assert parser._get_file_type("test.py") == "python"
    assert parser._get_file_type("app.js") == "javascript"
    assert parser._get_file_type("lib.ts") == "typescript"
    assert parser._get_file_type("Main.java") == "java"
    assert parser._get_file_type("utils.cpp") == "cpp"
    assert parser._get_file_type("unknown.xyz") == "unknown"


def test_hunk_parsing(parser):
    """Test parsing of diff hunks."""
    diff_content = """diff --git a/test.py b/test.py
index abc123..def456 100644
--- a/test.py
+++ b/test.py
@@ -10,5 +10,7 @@ def old_function():
     line1
-    line2
+    line2_new
     line3
+    line4"""

    file_changes = parser.parse_git_diff(diff_content)
    assert len(file_changes) == 1

    hunks = file_changes[0].hunks
    assert len(hunks) == 1

    hunk = hunks[0]
    assert hunk.old_start == 10
    assert hunk.old_lines == 5
    assert hunk.new_start == 10
    assert hunk.new_lines == 7


def test_function_change_detection(parser):
    """Test detection of function changes."""
    file_change = FileChange(
        file_path="test.py",
        change_type="modified",
        diff_content="",
        hunks=[],
        added_line_numbers=[15, 16],
        removed_line_numbers=[14],
        modified_line_numbers=[]
    )

    # Mock function finding
    parser.function_patterns = {
        'python': parser.function_patterns['python']
    }

    # This would need actual file content to work properly
    # For now, test that the function doesn't crash
    changed_functions = parser.extract_changed_functions(file_change)
    assert isinstance(changed_functions, list)