"""Git diff parser for analyzing code changes and extracting modified functions."""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path


@dataclass
class DiffHunk:
    """Represents a hunk in a git diff."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: List[str]  # The actual diff lines


@dataclass
class FileChange:
    """Represents changes in a single file."""

    file_path: str
    change_type: str  # 'added', 'deleted', 'modified', 'renamed'
    diff_content: str
    hunks: List[DiffHunk]
    added_line_numbers: List[int]
    removed_line_numbers: List[int]
    modified_line_numbers: List[int]


@dataclass
class FunctionChange:
    """Represents a function that has been modified."""

    function_name: str
    file_path: str
    change_type: str  # 'modified', 'added', 'deleted'
    affected_lines: List[int]
    old_function_range: Optional[Tuple[int, int]]
    new_function_range: Optional[Tuple[int, int]]


class GitDiffParser:
    """Parser for git diff output that extracts function-level changes."""

    def __init__(self):
        self.function_patterns = {
            'python': re.compile(r'^\s*(def|async def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE),
            'javascript': re.compile(r'^\s*(function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)|(const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=)', re.MULTILINE),
            'typescript': re.compile(r'^\s*(function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)|(const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=)', re.MULTILINE),
            'java': re.compile(r'^\s*(public|private|protected)?\s*(static)?\s*(\w+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', re.MULTILINE),
            'cpp': re.compile(r'^\s*(\w+\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(const)?\s*(?:\{|$)', re.MULTILINE),
        }

    def parse_git_diff(self, diff_content: str) -> List[FileChange]:
        """
        Parse a git diff string and extract file changes.

        Args:
            diff_content: The git diff output string

        Returns:
            List of FileChange objects representing each modified file
        """
        if not diff_content:
            return []

        # Split diff into file sections
        file_sections = self._split_diff_into_files(diff_content)

        file_changes = []
        for section in file_sections:
            file_change = self._parse_file_section(section)
            if file_change:
                file_changes.append(file_change)

        return file_changes

    def extract_changed_functions(self, file_change: FileChange) -> List[FunctionChange]:
        """
        Extract functions that are affected by the changes.

        Args:
            file_change: FileChange object containing the diff

        Returns:
            List of FunctionChange objects
        """
        # Determine file type for function detection
        file_type = self._get_file_type(file_change.file_path)

        if file_type not in self.function_patterns:
            return []

        # Get the complete file content (we'll need to parse original)
        file_content = self._reconstruct_file_content(file_change)

        # Find functions in the file
        all_functions = self._find_functions_in_content(file_content, file_type)

        # Determine which functions are affected
        affected_functions = []
        for func_name, func_range in all_functions.items():
            if self._is_function_affected(func_range, file_change):
                func_change = FunctionChange(
                    function_name=func_name,
                    file_path=file_change.file_path,
                    change_type=self._determine_change_type(file_change, func_range),
                    affected_lines=self._get_affected_lines_in_function(func_range, file_change),
                    old_function_range=None,  # Would need git show to get this
                    new_function_range=func_range
                )
                affected_functions.append(func_change)

        return affected_functions

    def get_changed_line_numbers(self, diff_content: str) -> Dict[str, List[int]]:
        """
        Extract all changed line numbers from a git diff.

        Args:
            diff_content: The git diff output string

        Returns:
            Dictionary mapping file paths to lists of changed line numbers
        """
        file_changes = self.parse_git_diff(diff_content)

        result = {}
        for file_change in file_changes:
            result[file_change.file_path] = (
                file_change.added_line_numbers +
                file_change.removed_line_numbers +
                file_change.modified_line_numbers
            )

        return result

    def _split_diff_into_files(self, diff_content: str) -> List[str]:
        """Split diff content into sections per file."""
        # Git diff starts with lines like "diff --git a/file.py b/file.py"
        file_pattern = re.compile(r'^diff --git a/(.+?) b/(.+?)$', re.MULTILINE)

        sections = []
        matches = list(file_pattern.finditer(diff_content))

        if not matches:
            return [diff_content] if diff_content.strip() else []

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(diff_content)
            sections.append(diff_content[start:end].strip())

        return sections

    def _parse_file_section(self, section: str) -> Optional[FileChange]:
        """Parse a single file section from the diff."""
        lines = section.split('\n')
        if not lines:
            return None

        # Extract file path and change type
        file_path = None
        change_type = 'modified'

        for line in lines:
            if line.startswith('diff --git'):
                # Extract path from "diff --git a/file.py b/file.py"
                parts = line.split()
                if len(parts) >= 4:
                    file_path = parts[3][2:]  # Remove "b/" prefix

            elif line.startswith('new file mode'):
                change_type = 'added'
            elif line.startswith('deleted file mode'):
                change_type = 'deleted'
            elif line.startswith('rename from'):
                change_type = 'renamed'

        if not file_path:
            return None

        # Parse hunks
        hunks = self._parse_hunks(lines)

        # Extract line numbers
        added_lines, removed_lines, modified_lines = self._extract_line_numbers(hunks)

        return FileChange(
            file_path=file_path,
            change_type=change_type,
            diff_content=section,
            hunks=hunks,
            added_line_numbers=added_lines,
            removed_line_numbers=removed_lines,
            modified_line_numbers=modified_lines
        )

    def _parse_hunks(self, lines: List[str]) -> List[DiffHunk]:
        """Parse diff hunks from file section."""
        hunks = []
        current_hunk_lines = []

        for line in lines:
            if line.startswith('@@'):
                # Start of new hunk
                if current_hunk_lines:
                    hunk = self._parse_hunk_header(current_hunk_lines[0], current_hunk_lines[1:])
                    if hunk:
                        hunks.append(hunk)

                current_hunk_lines = [line]
            elif current_hunk_lines:
                current_hunk_lines.append(line)

        # Add the last hunk
        if current_hunk_lines:
            hunk = self._parse_hunk_header(current_hunk_lines[0], current_hunk_lines[1:])
            if hunk:
                hunks.append(hunk)

        return hunks

    def _parse_hunk_header(self, header_line: str, content_lines: List[str]) -> Optional[DiffHunk]:
        """Parse a single hunk from header and content."""
        # Parse header like "@@ -10,7 +10,7 @@"
        match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', header_line)
        if not match:
            return None

        old_start = int(match.group(1))
        old_lines = int(match.group(2) or 1)
        new_start = int(match.group(3))
        new_lines = int(match.group(4) or 1)

        return DiffHunk(
            old_start=old_start,
            old_lines=old_lines,
            new_start=new_start,
            new_lines=new_lines,
            lines=content_lines
        )

    def _extract_line_numbers(self, hunks: List[DiffHunk]) -> Tuple[List[int], List[int], List[int]]:
        """Extract added, removed, and modified line numbers from hunks."""
        added_lines = []
        removed_lines = []
        modified_lines = []

        for hunk in hunks:
            current_old_line = hunk.old_start
            current_new_line = hunk.new_start

            for line in hunk.lines:
                if line.startswith('+') and not line.startswith('+++'):
                    added_lines.append(current_new_line)
                    current_new_line += 1
                elif line.startswith('-') and not line.startswith('---'):
                    removed_lines.append(current_old_line)
                    current_old_line += 1
                else:
                    # Context line - could be considered modified
                    if current_old_line == current_new_line:
                        modified_lines.append(current_new_line)
                    current_old_line += 1
                    current_new_line += 1

        return added_lines, removed_lines, modified_lines

    def _get_file_type(self, file_path: str) -> str:
        """Determine file type based on extension."""
        suffix = Path(file_path).suffix.lower()

        type_mapping = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.cxx': 'cpp',
            '.cc': 'cpp',
            '.c': 'cpp',
            '.h': 'cpp',
            '.hpp': 'cpp',
        }

        return type_mapping.get(suffix, 'unknown')

    def _reconstruct_file_content(self, file_change: FileChange) -> str:
        """
        Attempt to reconstruct the file content from diff.
        This is a simplified version - in practice, you might want to use git show.
        """
        # For now, return the diff content. In a real implementation,
        # you'd want to get the actual file content
        return file_change.diff_content

    def _find_functions_in_content(self, content: str, file_type: str) -> Dict[str, Tuple[int, int]]:
        """Find all functions in the content with their line ranges."""
        functions = {}
        pattern = self.function_patterns.get(file_type)

        if not pattern:
            return functions

        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            match = pattern.search(line)
            if match:
                if file_type == 'python':
                    func_name = match.group(2)
                elif file_type in ['javascript', 'typescript']:
                    func_name = match.group(2) or match.group(4)
                elif file_type == 'java':
                    func_name = match.group(4)
                elif file_type == 'cpp':
                    func_name = match.group(2)
                else:
                    continue

                if func_name:
                    # Simplified: assume function extends to next function or end
                    # In practice, you'd need more sophisticated parsing
                    functions[func_name] = (line_num, line_num + 10)  # Estimate

        return functions

    def _is_function_affected(self, func_range: Tuple[int, int], file_change: FileChange) -> bool:
        """Check if a function is affected by file changes."""
        start_line, end_line = func_range

        all_changed_lines = (
            file_change.added_line_numbers +
            file_change.removed_line_numbers +
            file_change.modified_line_numbers
        )

        return any(start_line <= line <= end_line for line in all_changed_lines)

    def _determine_change_type(self, file_change: FileChange, func_range: Tuple[int, int]) -> str:
        """Determine the type of change for a function."""
        start_line, end_line = func_range

        has_additions = any(start_line <= line <= end_line for line in file_change.added_line_numbers)
        has_removals = any(start_line <= line <= end_line for line in file_change.removed_line_numbers)

        if has_additions and has_removals:
            return 'modified'
        elif has_additions:
            return 'added'
        elif has_removals:
            return 'deleted'
        else:
            return 'modified'

    def _get_affected_lines_in_function(self, func_range: Tuple[int, int], file_change: FileChange) -> List[int]:
        """Get all affected line numbers within a function range."""
        start_line, end_line = func_range

        all_changed_lines = (
            file_change.added_line_numbers +
            file_change.removed_line_numbers +
            file_change.modified_line_numbers
        )

        return [line for line in all_changed_lines if start_line <= line <= end_line]


def parse_diff_string(diff_content: str) -> List[FileChange]:
    """
    Convenience function to parse a git diff string.

    Args:
        diff_content: The git diff output string

    Returns:
        List of FileChange objects
    """
    parser = GitDiffParser()
    return parser.parse_git_diff(diff_content)


def extract_changed_line_numbers_from_diff(diff_content: str) -> Dict[str, List[int]]:
    """
    Convenience function to extract changed line numbers from git diff.

    Args:
        diff_content: The git diff output string

    Returns:
        Dictionary mapping file paths to lists of changed line numbers
    """
    parser = GitDiffParser()
    return parser.get_changed_line_numbers(diff_content)