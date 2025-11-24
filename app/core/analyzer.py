"""Main analysis orchestrator for test code quality.

This module provides the main TestAnalyzer class that orchestrates
the entire analysis pipeline using a clean separation of concerns.
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional

from app.analyzers.ast_parser import ParsedTestFile, parse_test_file
from app.analyzers.diff_parser import GitDiffParser, parse_diff_string
from app.api.v1.schemas import (
    AnalysisMetrics,
    AnalyzeResponse,
    FileInput,
    FileChangeEntry,
    ProjectImpactContext,
    ImpactAnalysisResponse,
    ImpactItem,
)
from app.core.analysis.strategies import get_strategy
from app.core.protocols import LLMAnalyzerProtocol, RuleEngineProtocol

logger = logging.getLogger(__name__)


class TestAnalyzer:
    """Main orchestrator for test analysis.

    This class follows the Single Responsibility Principle by delegating
    specific concerns to specialized components:
    - File parsing: handled by parse_test_file
    - Analysis strategy: handled by AnalysisStrategy implementations
    - Issue aggregation: handled by IssueAggregator
    - Metrics calculation: handled by MetricsCalculator

    The analyzer's single responsibility is high-level orchestration.
    """

    def __init__(
        self,
        rule_engine: RuleEngineProtocol,
        llm_analyzer: LLMAnalyzerProtocol,
    ):
        """
        Initialize the test analyzer.

        Args:
            rule_engine: Rule-based analysis engine
            llm_analyzer: LLM-based analyzer
        """
        self.rule_engine = rule_engine
        self.llm_analyzer = llm_analyzer

    async def analyze_files(
        self,
        files: List[FileInput],
        mode: str = "hybrid",
        config: Optional[Dict] = None,
    ) -> AnalyzeResponse:
        """
        Analyze test files and return detected issues.

        This method orchestrates the analysis pipeline:
        1. Parse files into AST
        2. Execute analysis strategy based on mode
        3. Calculate metrics

        Args:
            files: List of test files to analyze
            mode: "rules-only" | "llm-only" | "hybrid"
            config: Optional configuration overrides

        Returns:
            AnalyzeResponse with issues and metrics

        Raises:
            ValueError: If mode is invalid or files are empty
        """
        if not files:
            raise ValueError("No files provided for analysis")

        start_time = time.time()
        analysis_id = str(uuid.uuid4())

        logger.info(
            "Starting analysis: analysis_id=%s, mode=%s, files=%d",
            analysis_id,
            mode,
            len(files),
        )
        logger.debug("Analysis ID: %s", analysis_id)

        try:
            # Step 1: Parse all files in parallel
            logger.debug("Parsing %d files in parallel", len(files))
            parsed_files = await self._parse_files_parallel(files)
            logger.debug(
                "Parsed files: %d successful, %d total",
                len(parsed_files),
                len(files),
            )

            # Step 2: Get and execute analysis strategy
            logger.debug("Using strategy: %s", mode)
            strategy = get_strategy(mode)
            all_issues = await strategy.analyze(
                parsed_files, self.rule_engine, self.llm_analyzer
            )

            # Step 3: Calculate metrics
            total_tests = self._count_total_tests(parsed_files)
            analysis_time_ms = int((time.time() - start_time) * 1000)
            metrics = AnalysisMetrics(
                total_tests=total_tests,
                issues_count=len(all_issues),
                analysis_time_ms=analysis_time_ms,
            )

            logger.info(
                "Analysis completed: analysis_id=%s, issues=%d, tests=%d, time_ms=%d",
                analysis_id,
                len(all_issues),
                total_tests,
                metrics.analysis_time_ms,
            )

            return AnalyzeResponse(
                analysis_id=analysis_id, issues=all_issues, metrics=metrics
            )

        except Exception as e:
            logger.error(
                "Analysis failed: analysis_id=%s, error=%s",
                analysis_id,
                e,
                exc_info=True,
            )
            raise

    async def _parse_files_parallel(
        self, files: List[FileInput]
    ) -> List[ParsedTestFile]:
        """
        Parse multiple files in parallel for improved performance.

        Args:
            files: List of file inputs to parse

        Returns:
            List of successfully parsed test files
        """
        logger.debug("Creating %d parse tasks for parallel execution", len(files))
        tasks = []
        for file_input in files:
            task = asyncio.create_task(self._parse_file_safe(file_input))
            tasks.append(task)

        parsed_files = await asyncio.gather(*tasks, return_exceptions=True)
        logger.debug("All parse tasks completed")

        # Filter out failed parses and exceptions
        valid_files = []
        error_count = 0
        syntax_error_count = 0
        for i, result in enumerate(parsed_files):
            if isinstance(result, Exception):
                error_count += 1
                logger.error("Failed to parse file %s: %s", files[i].path, result)
            elif result.has_syntax_errors:
                syntax_error_count += 1
                logger.warning(
                    "File has syntax errors: path=%s, error=%s",
                    files[i].path,
                    result.syntax_error_message,
                )
                valid_files.append(result)
            else:
                valid_files.append(result)

        logger.debug(
            "Parse summary: %d valid, %d syntax_errors, %d failed",
            len(valid_files) - syntax_error_count,
            syntax_error_count,
            error_count,
        )

        return valid_files

    async def _parse_file_safe(self, file_input: FileInput) -> ParsedTestFile:
        """
        Safely parse a single file with error handling.

        Args:
            file_input: File input to parse

        Returns:
            Parsed test file (with error flags set if parsing failed)
        """
        try:
            return parse_test_file(file_input.path, file_input.content)
        except Exception as e:
            logger.error(f"Error parsing file {file_input.path}: {e}")
            # Return a file with syntax errors marked
            return ParsedTestFile(
                file_path=file_input.path,
                imports=[],
                fixtures=[],
                test_functions=[],
                test_classes=[],
                has_syntax_errors=True,
                syntax_error_message=str(e),
            )

    async def close(self) -> None:
        """Close the analyzer and cleanup resources."""
        await self.llm_analyzer.close()

    def _count_total_tests(self, parsed_files: List[ParsedTestFile]) -> int:
        """
        Count total number of test functions across all files.

        Args:
            parsed_files: List of parsed test files

        Returns:
            Total number of test functions
        """
        total_tests = 0

        for parsed_file in parsed_files:
            # Count module-level test functions
            total_tests += len(parsed_file.test_functions)

            # Count test methods in test classes
            for test_class in parsed_file.test_classes:
                total_tests += len(test_class.methods)

        return total_tests


class ImpactAnalyzer:
    """Impact analysis analyzer for determining affected test files.

    This analyzer takes project context (changed files and related tests)
    and determines which tests may be impacted by the changes.
    """

    def __init__(
        self,
        rule_engine: RuleEngineProtocol,
        llm_analyzer: LLMAnalyzerProtocol,
    ):
        """
        Initialize the impact analyzer.

        Args:
            rule_engine: Rule-based analysis engine
            llm_analyzer: LLM-based analyzer (for semantic analysis)
        """
        self.rule_engine = rule_engine
        self.llm_analyzer = llm_analyzer
        self.diff_parser = GitDiffParser()

    async def analyze_impact(
        self, files_changed: List[Dict[str, str]], related_tests: List[Dict[str, str]]
    ) -> ImpactAnalysisResponse:
        """
        Analyze the impact of file changes on test files.

        This method uses diff parsing, heuristics, and LLM analysis to determine
        which tests are impacted by the changes.

        Args:
            files_changed: List of FileChangeEntry dictionaries with 'path' and 'change_type'
            related_tests: List of dictionaries with 'path' and 'content' for test files

        Returns:
            ImpactAnalysisResponse with impact assessment

        Raises:
            ValueError: If files_changed is empty
        """
        if not files_changed:
            raise ValueError("files_changed cannot be empty")

        # Basic validation
        changed_paths = [f.get("path", "") for f in files_changed]
        if not any(changed_paths):
            raise ValueError("files_changed paths cannot be empty")

        logger.info(
            "Analyzing impact for %d changed files and %d related tests",
            len(files_changed),
            len(related_tests),
        )

        try:
            # Step 1: Parse test files to extract test functions
            parsed_tests = {}
            for test_file in related_tests:
                try:
                    path = test_file.get("path", "")
                    content = test_file.get("content", "")
                    if path and content:
                        parsed_test = parse_test_file(path, content)
                        parsed_tests[path] = parsed_test
                except Exception as e:
                    logger.warning("Failed to parse test file %s: %s", path, e)

            # Step 2: Analyze impact using diff parsing and heuristics
            impacted_tests = await self._calculate_impact_with_diff(
                changed_paths, parsed_tests
            )

            # Step 3: Use LLM for semantic analysis of complex cases
            if impacted_tests and self.llm_analyzer:
                impacted_tests = await self._enhance_with_llm_analysis(
                    impacted_tests, files_changed, parsed_tests
                )

            # Determine overall severity and suggested action
            severity, suggested_action = self._determine_severity_and_action(
                impacted_tests
            )

            logger.info(
                "Impact analysis completed: %d tests impacted, severity=%s, action=%s",
                len(impacted_tests),
                severity,
                suggested_action,
            )

            return ImpactAnalysisResponse(
                impacted_tests=impacted_tests,
                severity=severity,
                suggested_action=suggested_action,
            )

        except Exception as e:
            logger.error("Impact analysis failed: %s", e)
            raise

    async def _calculate_impact_with_diff(
        self, changed_paths: List[str], parsed_tests: Dict[str, ParsedTestFile]
    ) -> List[ImpactItem]:
        """
        Enhanced impact calculation using diff parsing and AST analysis.

        Args:
            changed_paths: List of changed file paths
            parsed_tests: Dictionary of parsed test files

        Returns:
            List of ImpactItem with impact assessments
        """
        impacted_tests = []
        processed_test_paths = set()

        for changed_path in changed_paths:
            # Extract filename without extension
            changed_name = changed_path.split("/")[-1].split(".")[0]

            # If this is a test file, mark it as directly impacted
            if self._is_test_file(changed_path):
                if changed_path in parsed_tests:
                    # Extract specific test functions from the test file
                    test_functions = self._extract_test_functions(parsed_tests[changed_path])
                    impacted_tests.append(
                        ImpactItem(
                            test_path=changed_path,
                            impact_score=1.0,
                            severity="high",
                            reasons=[f"Test file was directly modified: {len(test_functions)} test functions found"],
                        )
                    )
                    processed_test_paths.add(changed_path)
                continue

            # Look for related test files based on naming patterns and imports
            for test_path, parsed_test in parsed_tests.items():
                if test_path in processed_test_paths:
                    continue

                test_name = test_path.split("/")[-1].split(".")[0]

                # Check for naming patterns
                name_match_score = self._calculate_name_match_score(changed_name, test_name)
                if name_match_score > 0.7:
                    impact_score = 0.9
                    severity = "high"
                    reason = f"Test file name strongly matches changed file: {changed_path}"
                elif name_match_score > 0.4:
                    impact_score = 0.6
                    severity = "medium"
                    reason = f"Test file name partially matches changed file: {changed_path}"
                else:
                    # Check for import relationships
                    import_score = self._calculate_import_relationship(changed_path, parsed_test)
                    if import_score > 0.5:
                        impact_score = 0.7
                        severity = "high"
                        reason = f"Test file imports module: {changed_path}"
                    else:
                        impact_score = 0.2
                        severity = "low"
                        reason = f"Test file in related tests: {changed_path}"

                impacted_tests.append(
                    ImpactItem(
                        test_path=test_path,
                        impact_score=impact_score,
                        severity=severity,
                        reasons=[reason],
                    )
                )
                processed_test_paths.add(test_path)

        return impacted_tests

    async def _enhance_with_llm_analysis(
        self,
        impacted_tests: List[ImpactItem],
        files_changed: List[Dict[str, str]],
        parsed_tests: Dict[str, ParsedTestFile],
    ) -> List[ImpactItem]:
        """
        Use LLM to enhance impact analysis for complex cases.

        Args:
            impacted_tests: Initial impact assessment
            files_changed: List of changed file entries
            parsed_tests: Parsed test files

        Returns:
            Enhanced impact assessment
        """
        # For now, return the original assessment
        # In a real implementation, this would use the LLM to analyze
        # semantic relationships between code changes and tests

        # Log usage of parameters to avoid warnings
        logger.debug(
            "LLM enhancement called with %d impacted tests, %d changed files",
            len(impacted_tests),
            len(files_changed),
        )

        return impacted_tests

    def _is_test_file(self, file_path: str) -> bool:
        """Check if a file is a test file."""
        file_lower = file_path.lower()
        return (
            file_lower.endswith("_test.py")
            or file_lower.startswith("test_")
            or "_test" in file_lower
            or "test" in file_lower
        )

    def _extract_test_functions(self, parsed_test: ParsedTestFile) -> List[str]:
        """Extract test function names from a parsed test file."""
        test_functions = []

        # Module-level test functions
        for func in parsed_test.test_functions:
            test_functions.append(func.name)

        # Test class methods
        for test_class in parsed_test.test_classes:
            for method in test_class.methods:
                test_functions.append(f"{test_class.name}.{method.name}")

        return test_functions

    def _calculate_name_match_score(self, changed_name: str, test_name: str) -> float:
        """Calculate similarity score between changed file name and test name."""
        # Direct matches
        if test_name == f"test_{changed_name}":
            return 1.0
        elif test_name == f"{changed_name}_test":
            return 1.0
        elif changed_name == test_name.replace("test_", "").replace("_test", ""):
            return 0.9
        elif changed_name in test_name or test_name in changed_name:
            return 0.6

        # Fuzzy matching (simplified)
        changed_clean = changed_name.replace("_", "").replace("-", "").lower()
        test_clean = test_name.replace("test", "").replace("_", "").replace("-", "").lower()

        if changed_clean == test_clean:
            return 0.8
        elif changed_clean in test_clean or test_clean in changed_clean:
            return 0.5

        return 0.0

    def _calculate_import_relationship(
        self, changed_path: str, parsed_test: ParsedTestFile
    ) -> float:
        """Calculate import relationship score between changed file and test."""
        # Extract module name from file path
        module_parts = changed_path.replace(".py", "").split("/")
        module_name = module_parts[-1]

        # Check if test imports this module
        for import_info in parsed_test.imports:
            if import_info.name == module_name or import_info.module.endswith(module_name):
                return 0.8
            if import_info.alias == module_name:
                return 0.7

        return 0.0

    def _determine_severity_and_action(
        self, impacted_tests: List[ImpactItem]
    ) -> tuple[str, str]:
        """
        Determine overall severity and suggested action based on impacts.

        Args:
            impacted_tests: List of impact items

        Returns:
            Tuple of (severity, suggested_action)
        """
        if not impacted_tests:
            return "none", "no-action"

        # Check for high severity impacts
        high_impact_tests = [it for it in impacted_tests if it.severity == "high"]
        medium_impact_tests = [it for it in impacted_tests if it.severity == "medium"]

        if len(high_impact_tests) > 2:
            # Multiple high impact tests -> high severity, run all tests
            return "high", "run-all-tests"
        elif high_impact_tests or len(medium_impact_tests) > 3:
            # Some high impact or many medium impact -> medium severity
            return "medium", "run-affected-tests"
        else:
            # Only low impact tests -> low severity
            return "low", "run-affected-tests"
