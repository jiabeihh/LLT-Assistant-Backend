"""JSON cleaning utilities for LLM responses.

LLMs often return JSON wrapped in Markdown code blocks or with extra formatting.
This module provides utilities to clean and extract pure JSON.
"""

import json
import re
from typing import Any, Dict, Optional, Union


class JSONCleaner:
    """Utilities for cleaning LLM-generated JSON responses."""

    # Patterns to identify and clean JSON from LLM responses
    MARKDOWN_CODE_BLOCK_PATTERN = re.compile(
        r'```(?:json)?\s*(.*?)\s*```',
        re.DOTALL | re.IGNORECASE
    )

    # Common LLM prefixes/suffixes that need to be removed
    PREFIX_PATTERNS = [
        r'^Here is the (JSON|response|result):\s*',
        r'^The (JSON|response|result) is:\s*',
        r'^(Here\'s|Here is) the (JSON|response|result):\s*',
        r'^Response:\s*',
        r'^Result:\s*',
        r'^Output:\s*',
        r'^```json\s*',
    ]

    SUFFIX_PATTERNS = [
        r'\s*```$',
        r'\s*(Note|Explanation|Details):.*$',
        r'\s*This is.*$',
    ]

    # Pattern to fix common JSON syntax errors
    TRAILING_COMMAS_PATTERN = re.compile(r',\s*([}\]])')

    def clean_json_response(self, response: str) -> str:
        """
        Clean LLM response to extract pure JSON.

        Args:
            response: Raw response from LLM

        Returns:
            Cleaned JSON string

        Raises:
            ValueError: If no JSON content can be found
        """
        if not response or not response.strip():
            raise ValueError("Empty response provided")

        cleaned = response.strip()

        # Step 1: Extract JSON from Markdown code blocks
        cleaned = self._extract_from_markdown(cleaned)

        # Step 2: Remove common prefixes
        cleaned = self._remove_prefixes(cleaned)

        # Step 3: Remove common suffixes
        cleaned = self._remove_suffixes(cleaned)

        # Step 4: Fix common syntax errors
        cleaned = self._fix_syntax_errors(cleaned)

        # Step 5: Validate that it's parseable JSON
        if not self._is_valid_json(cleaned):
            raise ValueError(f"Cleaned response is not valid JSON: {cleaned}")

        return cleaned

    def try_clean_and_parse(self, response: str) -> Dict[str, Any]:
        """
        Attempt to clean and parse JSON response.

        Args:
            response: Raw response from LLM

        Returns:
            Parsed JSON as dictionary

        Raises:
            ValueError: If JSON cannot be parsed after cleaning
        """
        try:
            # First try to parse as-is
            return json.loads(response)
        except json.JSONDecodeError:
            # Try cleaning first
            try:
                cleaned_json = self.clean_json_response(response)
                return json.loads(cleaned_json)
            except Exception as e:
                # If cleaning fails, try more aggressive cleaning
                try:
                    aggressive_cleaned = self._aggressive_cleaning(response)
                    return json.loads(aggressive_cleaned)
                except Exception as final_e:
                    raise ValueError(f"Failed to parse JSON after all cleaning attempts: {final_e}")

    def _extract_from_markdown(self, text: str) -> str:
        """Extract JSON from Markdown code blocks."""
        match = self.MARKDOWN_CODE_BLOCK_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        return text

    def _remove_prefixes(self, text: str) -> str:
        """Remove common LLM response prefixes."""
        cleaned = text
        for pattern in self.PREFIX_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _remove_suffixes(self, text: str) -> str:
        """Remove common LLM response suffixes."""
        cleaned = text
        for pattern in self.SUFFIX_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        return cleaned.strip()

    def _fix_syntax_errors(self, text: str) -> str:
        """Fix common JSON syntax errors."""
        # Remove trailing commas before closing brackets/braces
        cleaned = self.TRAILING_COMMAS_PATTERN.sub(r'\1', text)

        # Fix quotes - replace single quotes with double quotes (carefully)
        cleaned = self._fix_quotes(cleaned)

        # Fix escaped characters
        cleaned = self._fix_escaped_characters(cleaned)

        return cleaned.strip()

    def _fix_quotes(self, text: str) -> str:
        """
        Fix quote issues in JSON.

        This is a simplified approach - in practice, quote fixing
        is complex and may need more sophisticated handling.
        """
        # Simple pattern to replace single quotes around values
        # This is conservative to avoid breaking valid JSON
        pattern = re.compile(r"'([^']*)'(?=\s*[,}\]])")
        return pattern.sub(r'"\1"', text)

    def _fix_escaped_characters(self, text: str) -> str:
        """Fix common escaped character issues."""
        # Fix double-escaped newlines
        text = text.replace('\\n', '\\\\n')

        # Fix double-escaped tabs
        text = text.replace('\\t', '\\\\t')

        return text

    def _is_valid_json(self, text: str) -> bool:
        """Check if text is valid JSON."""
        try:
            json.loads(text)
            return True
        except json.JSONDecodeError:
            return False

    def _aggressive_cleaning(self, response: str) -> str:
        """
        More aggressive cleaning for difficult cases.

        Args:
            response: Raw response text

        Returns:
            Aggressively cleaned JSON string
        """
        # Remove all non-JSON content outside of braces/brackets
        cleaned = response.strip()

        # Find the first { or [ and the last } or ]
        start_idx = None
        end_idx = None

        for i, char in enumerate(cleaned):
            if char in '{[':
                start_idx = i
                break

        if start_idx is not None:
            # Find matching closing bracket/brace
            bracket_stack = []
            opening_char = cleaned[start_idx]
            closing_char = '}' if opening_char == '{' else ']'

            bracket_stack.append(opening_char)

            for i in range(start_idx + 1, len(cleaned)):
                char = cleaned[i]
                if char == opening_char:
                    bracket_stack.append(char)
                elif char == closing_char:
                    if bracket_stack and bracket_stack[-1] == opening_char:
                        bracket_stack.pop()
                        if not bracket_stack:
                            end_idx = i + 1
                            break
                    else:
                        # Mismatched bracket, but let's take what we have
                        end_idx = i + 1
                        break

        if start_idx is not None and end_idx is not None:
            cleaned = cleaned[start_idx:end_idx]

        # Apply basic cleaning
        cleaned = self._fix_syntax_errors(cleaned)

        return cleaned.strip()


def clean_llm_json(response: str) -> str:
    """
    Convenience function to clean LLM JSON response.

    Args:
        response: Raw response from LLM

    Returns:
        Cleaned JSON string

    Raises:
        ValueError: If JSON cannot be extracted
    """
    cleaner = JSONCleaner()
    return cleaner.clean_json_response(response)


def parse_llm_json(response: str) -> Dict[str, Any]:
    """
    Convenience function to parse LLM JSON response.

    Args:
        response: Raw response from LLM

    Returns:
        Parsed JSON dictionary

    Raises:
        ValueError: If JSON cannot be parsed
    """
    cleaner = JSONCleaner()
    return cleaner.try_clean_and_parse(response)