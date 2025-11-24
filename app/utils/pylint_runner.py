"""Pylint integration for Python code quality analysis.

This module provides utilities to run pylint on Python code and extract
quality issues with severity ratings and fix suggestions.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class PylintIssue:
    """Represents a pylint-detected issue."""

    def __init__(
        self,
        message_id: str,
        symbol: str,
        path: str,
        line: int,
        column: int,
        message: str,
        confidence: str,
    ):
        self.message_id = message_id
        self.symbol = symbol
        self.path = path
        self.line = line
        self.column = column
        self.message = message
        self.confidence = confidence

    @property
    def severity(self) -> str:
        """Map pylint confidence to severity levels."""
        if self.confidence in ("HIGH",):
            return "error"
        elif self.confidence in ("MEDIUM",):
            return "warning"
        else:
            return "info"

    @property
    def category(self) -> str:
        """Get issue category based on message_id."""
        if self.message_id.startswith("C"):
            return "convention"
        elif self.message_id.startswith("R"):
            return "refactor"
        elif self.message_id.startswith("W"):
            return "warning"
        elif self.message_id.startswith("E"):
            return "error"
        elif self.message_id.startswith("F"):
            return "fatal"
        else:
            return "info"


class PylintRunner:
    """Runner for pylint analysis with JSON output parsing."""

    def __init__(self, disable_checks: Optional[List[str]] = None):
        """
        Initialize pylint runner.

        Args:
            disable_checks: List of pylint checks to disable
        """
        # Default disabled checks for test files
        default_disabled = [
            "missing-module-docstring",
            "missing-function-docstring",
            "missing-class-docstring",
            "import-error",  # Can't resolve imports in isolated environment
            "no-member",  # Can't resolve types without full project context
        ]

        if disable_checks:
            self.disabled_checks = default_disabled + disable_checks
        else:
            self.disabled_checks = default_disabled

        # Check if pylint is available
        self._check_pylint_availability()

    def _check_pylint_availability(self):
        """Check if pylint is installed and available."""
        try:
            subprocess.run(
                ["pylint", "--version"],
                capture_output=True,
                check=True,
                timeout=10,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning("Pylint not available: %s", e)
            raise RuntimeError(
                "Pylint is required for quality analysis but is not installed. "
                "Install it with: pip install pylint"
            )

    def analyze_code(
        self,
        code: str,
        file_path: str = "<string>",
        additional_args: Optional[List[str]] = None,
    ) -> List[PylintIssue]:
        """
        Analyze Python code with pylint.

        Args:
            code: Python source code to analyze
            file_path: Path to use for reporting (helps with relative imports)
            additional_args: Additional pylint arguments

        Returns:
            List of PylintIssue objects

        Raises:
            RuntimeError: If pylint execution fails
        """
        if not code.strip():
            return []

        # Create temporary file for analysis
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        try:
            # Build pylint command
            cmd = self._build_pylint_command(temp_file_path, additional_args)

            # Run pylint
            logger.debug("Running pylint command: %s", " ".join(cmd))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
            )

            # Parse results
            issues = self._parse_pylint_output(result.stdout, result.stderr)

            logger.debug(
                "Pylint analysis completed: %d issues found, returncode=%d",
                len(issues),
                result.returncode,
            )

            return issues

        except subprocess.TimeoutExpired:
            logger.error("Pylint analysis timed out")
            raise RuntimeError("Pylint analysis timed out")
        except Exception as e:
            logger.error("Pylint analysis failed: %s", e)
            raise RuntimeError(f"Pylint analysis failed: {e}")
        finally:
            # Clean up temporary file
            try:
                Path(temp_file_path).unlink()
            except Exception:
                pass

    def _build_pylint_command(
        self, file_path: str, additional_args: Optional[List[str]] = None
    ) -> List[str]:
        """Build pylint command with appropriate arguments."""
        cmd = ["pylint"]

        # Output format
        cmd.extend(["--output-format=json"])

        # Disable specific checks
        if self.disabled_checks:
            disable_str = ",".join(self.disabled_checks)
            cmd.extend([f"--disable={disable_str}"])

        # Set confidence levels
        cmd.extend(["--confidence=HIGH,INFERENCE,INFERENCE_FAILURE,UNDEFINED"])

        # Additional arguments
        if additional_args:
            cmd.extend(additional_args)

        # File to analyze
        cmd.append(file_path)

        return cmd

    def _parse_pylint_output(self, stdout: str, stderr: str) -> List[PylintIssue]:
        """Parse pylint JSON output into PylintIssue objects."""
        issues = []

        # Pylint outputs JSON to stdout, but may also have regular text
        # Look for JSON array in the output
        if not stdout.strip():
            return []

        try:
            # Try to parse as JSON directly
            pylint_data = json.loads(stdout)
        except json.JSONDecodeError:
            # If direct parsing fails, try to extract JSON from mixed output
            try:
                lines = stdout.strip().split('\n')
                for line in lines:
                    if line.startswith('[') or line.startswith('{'):
                        pylint_data = json.loads(line)
                        break
                else:
                    # No JSON found, parse from stderr if it contains structured output
                    return self._parse_text_output(stderr)
            except Exception:
                # Fallback to text parsing
                return self._parse_text_output(stdout + stderr)

        # Ensure we have a list of issues
        if isinstance(pylint_data, dict):
            pylint_data = pylint_data.get("issues", [])

        for issue_data in pylint_data:
            try:
                issue = PylintIssue(
                    message_id=issue_data.get("message-id", ""),
                    symbol=issue_data.get("symbol", ""),
                    path=issue_data.get("path", ""),
                    line=issue_data.get("line", 0),
                    column=issue_data.get("column", 0),
                    message=issue_data.get("message", ""),
                    confidence=issue_data.get("confidence", ""),
                )
                issues.append(issue)
            except Exception as e:
                logger.warning("Failed to parse pylint issue: %s", e)

        return issues

    def _parse_text_output(self, output: str) -> List[PylintIssue]:
        """Parse pylint text output as fallback."""
        issues = []

        lines = output.split('\n')
        for line in lines:
            # Try to match pylint's default output format
            # Example: file.py:10,0: C0111: missing-docstring
            parts = line.strip().split(':')
            if len(parts) >= 4:
                try:
                    path = parts[0]
                    line_num = int(parts[1])
                    column = int(parts[2]) if ',' in parts[2] else 0
                    message_id = parts[3].strip().split()[0]
                    message = ':'.join(parts[3:]).strip().split(':', 1)[1] if ':' in ':'.join(parts[3:]).strip() else ""

                    issue = PylintIssue(
                        message_id=message_id,
                        symbol=message_id,
                        path=path,
                        line=line_num,
                        column=column,
                        message=message,
                        confidence="HIGH",  # Default for text output
                    )
                    issues.append(issue)
                except Exception as e:
                    logger.debug("Failed to parse text line '%s': %s", line, e)

        return issues

    def get_fix_suggestion(self, issue: PylintIssue) -> Optional[str]:
        """
        Generate fix suggestions for common pylint issues.

        Args:
            issue: PylintIssue to generate suggestion for

        Returns:
            Fix suggestion string or None
        """
        suggestions = {
            "C0111": "Add a docstring to explain the function's purpose",
            "C0112": "Improve the docstring to be more descriptive",
            "C0103": "Use a more descriptive variable name that follows snake_case convention",
            "C0200": "Consider using enumerate() instead of manual counter",
            "C0201": "Consider using a comprehension or filter()",
            "C0202": "Use a comprehension instead of a for loop",
            "C0203": "Use enumerate() instead of counter variable",
            "C0206": "Consider using a comprehension or list literal",
            "C0301": "Break this long line into multiple lines",
            "C0303": "Add trailing whitespace removal",
            "C0321": "Remove unnecessary semicolon",
            "C0326": "Add spaces around operators for better readability",
            "C0330": "Add proper indentation (4 spaces per level)",
            "W0603": "Avoid using global variables, consider passing as parameter",
            "W0702": "Be more specific about the exception type you catch",
            "W0703": "Be more specific about the exception type you catch",
            "R0902": "Consider breaking this class into smaller components",
            "R0903": "Consider adding methods if this class needs more functionality",
            "R0911": "Consider reducing the number of return statements",
            "R0912": "Consider breaking this function into smaller functions",
            "R0913": "Consider using a configuration object or reducing parameters",
            "R0914": "Consider using local functions to reduce variable count",
            "R0915": "Consider breaking this function into smaller functions",
        }

        return suggestions.get(issue.message_id)

    def analyze_multiple_files(
        self,
        files: Dict[str, str],
        additional_args: Optional[List[str]] = None,
    ) -> Dict[str, List[PylintIssue]]:
        """
        Analyze multiple Python files.

        Args:
            files: Dictionary mapping file paths to their content
            additional_args: Additional pylint arguments

        Returns:
            Dictionary mapping file paths to lists of issues
        """
        results = {}

        for file_path, code in files.items():
            try:
                issues = self.analyze_code(code, file_path, additional_args)
                results[file_path] = issues
            except Exception as e:
                logger.error("Failed to analyze file %s: %s", file_path, e)
                # Add an empty list to maintain file structure
                results[file_path] = []

        return results


def run_pylint_analysis(
    code: str, file_path: str = "<string>", disable_checks: Optional[List[str]] = None
) -> List[PylintIssue]:
    """
    Convenience function to run pylint on a single file.

    Args:
        code: Python source code
        file_path: File path for reporting
        disable_checks: List of checks to disable

    Returns:
        List of PylintIssue objects
    """
    runner = PylintRunner(disable_checks)
    return runner.analyze_code(code, file_path)


def is_pylint_available() -> bool:
    """
    Check if pylint is available in the environment.

    Returns:
        True if pylint is available, False otherwise
    """
    try:
        subprocess.run(
            ["pylint", "--version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False