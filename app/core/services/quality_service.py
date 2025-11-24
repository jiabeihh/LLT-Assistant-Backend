"""Batch quality analysis service for Feature 4.

This module provides QualityAnalysisService which handles batch analysis
of multiple test files for quality issues with fix suggestions.
"""

import logging
import time
import uuid
from typing import List, Optional

from app.analyzers.rule_engine import RuleEngine
from app.api.v1.schemas import (
    FileInput,
    FixSuggestion,
    QualityAnalysisResponse,
    QualityIssue,
    QualitySummary,
)
from app.core.analysis.llm_analyzer import LLMAnalyzer
from app.core.analyzer import TestAnalyzer
from app.core.llm.llm_client import create_llm_client
from app.utils.pylint_runner import PylintRunner, is_pylint_available

logger = logging.getLogger(__name__)


class QualityAnalysisService:
    """Service for batch quality analysis of test files.

    This service provides a simplified interface for analyzing multiple
    test files and returning quality issues with fix suggestions.
    """

    def __init__(self, test_analyzer: Optional[TestAnalyzer] = None):
        """
        Initialize the quality analysis service.

        Args:
            test_analyzer: Optional TestAnalyzer instance (will create if None)
        """
        if test_analyzer is None:
            rule_engine = RuleEngine()
            llm_client = create_llm_client()
            llm_analyzer = LLMAnalyzer(llm_client)
            self.test_analyzer = TestAnalyzer(rule_engine, llm_analyzer)
        else:
            self.test_analyzer = test_analyzer

        # Initialize pylint runner if available
        if is_pylint_available():
            try:
                self.pylint_runner = PylintRunner()
                logger.info("Pylint integration enabled for quality analysis")
            except Exception as e:
                logger.warning("Failed to initialize pylint runner: %s", e)
                self.pylint_runner = None
        else:
            logger.info("Pylint not available, using rule-based analysis only")
            self.pylint_runner = None

    async def analyze_batch(
        self, files: List[FileInput], mode: str = "hybrid"
    ) -> QualityAnalysisResponse:
        """
        Analyze multiple test files for quality issues.

        This method orchestrates the analysis of multiple files and converts
        the results to the Feature 4 Quality Analysis format.

        Args:
            files: List of test files to analyze
            mode: Analysis mode - "fast" (rules-only), "deep" (llm-only), or "hybrid"

        Returns:
            QualityAnalysisResponse with issues and summary

        Raises:
            ValueError: If files are empty or mode is invalid
        """
        if not files:
            raise ValueError("No files provided for analysis")

        start_time = time.time()
        analysis_id = str(uuid.uuid4())

        logger.info(
            "Starting quality analysis: analysis_id=%s, files=%d, mode=%s",
            analysis_id,
            len(files),
            mode,
        )
        logger.debug("Quality analysis files: %s", [f.path for f in files])

        try:
            # Convert mode to TestAnalyzer format
            analyzer_mode = self._convert_mode(mode)
            logger.debug("Converted mode: %s -> %s", mode, analyzer_mode)

            # Run pylint analysis if available and in fast mode
            pylint_issues = []
            if self.pylint_runner and mode == "fast":
                logger.debug("Running pylint analysis on %d files", len(files))
                pylint_issues = self._run_pylint_analysis(files)
                logger.debug("Pylint found %d additional issues", len(pylint_issues))

            # Perform analysis using existing TestAnalyzer
            logger.debug("Calling TestAnalyzer.analyze_files")
            analysis_result = await self.test_analyzer.analyze_files(
                files=files, mode=analyzer_mode
            )
            logger.debug(
                "TestAnalyzer returned %d raw issues", len(analysis_result.issues)
            )

            # Convert results to Quality Analysis format
            logger.debug("Converting issues to quality analysis format")
            test_analyzer_issues = self._convert_issues(analysis_result.issues)

            # Merge pylint and test analyzer issues
            quality_issues = self._merge_issues(test_analyzer_issues, pylint_issues)

            # Calculate summary statistics
            summary = self._calculate_summary(files, quality_issues)

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "Quality analysis completed: analysis_id=%s, issues=%d, time_ms=%d",
                analysis_id,
                len(quality_issues),
                elapsed_ms,
            )

            return QualityAnalysisResponse(
                analysis_id=analysis_id, summary=summary, issues=quality_issues
            )

        except Exception as e:
            logger.error(
                "Quality analysis failed: analysis_id=%s, error=%s",
                analysis_id,
                e,
                exc_info=True,
            )
            raise

    def _convert_mode(self, mode: str) -> str:
        """
        Convert Feature 4 mode to TestAnalyzer mode.

        Args:
            mode: Feature 4 mode (fast/deep/hybrid)

        Returns:
            TestAnalyzer mode (rules-only/llm-only/hybrid)
        """
        mode_mapping = {
            "fast": "rules-only",
            "deep": "llm-only",
            "hybrid": "hybrid",
        }

        if mode not in mode_mapping:
            raise ValueError(
                f"Invalid mode: {mode}. Must be one of {list(mode_mapping.keys())}"
            )

        return mode_mapping[mode]

    def _convert_issues(self, issues: List) -> List[QualityIssue]:
        """
        Convert TestAnalyzer issues to QualityIssue format.

        Args:
            issues: Issues from TestAnalyzer

        Returns:
            List of QualityIssue objects
        """
        quality_issues = []

        for issue in issues:
            # Convert suggestion if present
            suggestion = None
            if hasattr(issue, "suggestion") and issue.suggestion is not None:
                suggestion = self._convert_suggestion(issue.suggestion)

            # Map detected_by field
            detected_by = "rule" if issue.detected_by == "rule_engine" else "llm"

            quality_issue = QualityIssue(
                file_path=issue.file,
                line=issue.line,
                column=issue.column,
                severity=issue.severity,
                code=issue.type,
                message=issue.message,
                detected_by=detected_by,
                suggestion=suggestion,
            )
            quality_issues.append(quality_issue)

        return quality_issues

    def _convert_suggestion(self, suggestion) -> FixSuggestion:
        """
        Convert IssueSuggestion to FixSuggestion format.

        Args:
            suggestion: IssueSuggestion from TestAnalyzer

        Returns:
            FixSuggestion object
        """
        # Map action types
        action_mapping = {
            "replace": "replace",
            "remove": "delete",
            "add": "insert",
        }

        fix_type = action_mapping.get(suggestion.action, "replace")

        # For insert/add operations, use new_code
        # For replace, show both old and new
        # For delete, old_code contains what to delete
        new_text = suggestion.new_code

        return FixSuggestion(
            type=fix_type,
            new_text=new_text,
            description=suggestion.explanation,
        )

    def _calculate_summary(
        self, files: List[FileInput], issues: List[QualityIssue]
    ) -> QualitySummary:
        """
        Calculate summary statistics for the analysis.

        Args:
            files: List of analyzed files
            issues: List of detected issues

        Returns:
            QualitySummary with statistics
        """
        total_files = len(files)
        total_issues = len(issues)
        critical_issues = len([issue for issue in issues if issue.severity == "error"])

        return QualitySummary(
            total_files=total_files,
            total_issues=total_issues,
            critical_issues=critical_issues,
        )

    def _run_pylint_analysis(self, files: List[FileInput]) -> List[QualityIssue]:
        """
        Run pylint analysis on the provided files.

        Args:
            files: List of files to analyze

        Returns:
            List of QualityIssue objects from pylint
        """
        if not self.pylint_runner:
            return []

        issues = []
        for file_input in files:
            try:
                # Only analyze Python files
                if not file_input.path.endswith('.py'):
                    continue

                pylint_issues = self.pylint_runner.analyze_code(
                    file_input.content, file_input.path
                )

                for pylint_issue in pylint_issues:
                    # Convert pylint issue to QualityIssue
                    suggestion_text = self.pylint_runner.get_fix_suggestion(pylint_issue)

                    quality_issue = QualityIssue(
                        file_path=file_input.path,
                        line=pylint_issue.line,
                        column=pylint_issue.column,
                        severity=pylint_issue.severity,
                        code=pylint_issue.symbol,
                        message=pylint_issue.message,
                        detected_by="rule",  # Pylint is rule-based
                        suggestion=FixSuggestion(
                            type="replace",
                            new_text="",  # Pylint suggestions are descriptive
                            description=suggestion_text or f"Fix: {pylint_issue.message}",
                        ) if suggestion_text else None,
                    )
                    issues.append(quality_issue)

            except Exception as e:
                logger.warning("Pylint analysis failed for file %s: %s", file_input.path, e)

        return issues

    def _merge_issues(
        self, test_analyzer_issues: List[QualityIssue], pylint_issues: List[QualityIssue]
    ) -> List[QualityIssue]:
        """
        Merge issues from test analyzer and pylint, removing duplicates.

        Args:
            test_analyzer_issues: Issues from the test analyzer
            pylint_issues: Issues from pylint

        Returns:
            Merged list of unique issues
        """
        all_issues = test_analyzer_issues + pylint_issues

        # Remove duplicates based on file_path, line, and message
        seen_issues = set()
        unique_issues = []

        for issue in all_issues:
            # Create a key for deduplication
            key = (issue.file_path, issue.line, issue.code, issue.message[:100])  # First 100 chars

            if key not in seen_issues:
                seen_issues.add(key)
                unique_issues.append(issue)
            else:
                logger.debug(
                    "Deduplicating issue: %s:%d - %s", issue.file_path, issue.line, issue.code
                )

        return unique_issues

    async def close(self) -> None:
        """Close resources used by the service."""
        await self.test_analyzer.close()
