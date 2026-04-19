#!/usr/bin/env python3
"""
Diagnostic tools for metadata extraction
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .base import ExtractionResult


@dataclass
class DiagnosticReport:
    """Report for a single file diagnosis"""
    filepath: str
    success: bool
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: float = 0.0
    has_cover_art: bool = False
    picture_count: int = 0
    pictures: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    diagnostics: Dict = field(default_factory=dict)

    def to_summary(self) -> str:
        """Generate a human-readable summary"""
        lines = [
            f"File: {self.filepath}",
            f"  Status: {'OK' if self.success else 'FAILED'}",
        ]

        if self.title:
            lines.append(f"  Title: {self.title}")
        if self.artist:
            lines.append(f"  Artist: {self.artist}")
        if self.album:
            lines.append(f"  Album: {self.album}")
        if self.duration > 0:
            lines.append(f"  Duration: {self.duration:.2f}s")

        lines.append(f"  Cover Art: {'Yes' if self.has_cover_art else 'No'}")
        if self.pictures:
            for pic in self.pictures:
                lines.append(
                    f"    - {pic['type']}: {pic['size']} bytes ({pic['mime'] or 'unknown'})"
                )

        if self.errors:
            lines.append(f"  Errors: {self.errors}")
        if self.warnings:
            lines.append(f"  Warnings: {self.warnings}")

        return "\n".join(lines)


@dataclass
class DirectorySummary:
    """Summary of directory-wide diagnosis"""
    total_files: int = 0
    successful_extractions: int = 0
    files_with_cover_art: int = 0
    files_without_cover_art: int = 0
    files_with_errors: int = 0
    files_by_extension: Dict[str, int] = field(default_factory=dict)
    all_errors: List[str] = field(default_factory=list)
    all_warnings: List[str] = field(default_factory=list)

    @property
    def cover_art_percentage(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.files_with_cover_art / self.total_files) * 100

    def to_summary(self) -> str:
        """Generate a human-readable summary"""
        lines = [
            "Directory Summary",
            "=" * 40,
            f"Total files: {self.total_files}",
            f"Successful extractions: {self.successful_extractions}",
            f"Files with cover art: {self.files_with_cover_art} ({self.cover_art_percentage:.1f}%)",
            f"Files without cover art: {self.files_without_cover_art}",
            f"Files with errors: {self.files_with_errors}",
            "",
            "Files by extension:",
        ]
        for ext, count in sorted(self.files_by_extension.items()):
            lines.append(f"  {ext}: {count}")

        if self.all_errors:
            lines.append("")
            lines.append("Errors encountered:")
            for err in set(self.all_errors):
                lines.append(f"  - {err}")

        return "\n".join(lines)


class MetadataDiagnostic:
    """Diagnostic tool for analyzing metadata extraction"""

    SUPPORTED_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.mp4', '.m4b', '.m4p', '.ogg', '.oga'}

    def analyze_file(self, filepath: str) -> DiagnosticReport:
        """
        Analyze a single file and generate a diagnostic report.

        Args:
            filepath: Path to the audio file

        Returns:
            DiagnosticReport with detailed information
        """
        from . import get_extractor

        ext = Path(filepath).suffix.lower()
        extractor = get_extractor(filepath)

        if extractor is None:
            return DiagnosticReport(
                filepath=filepath,
                success=False,
                errors=[f"Unsupported file format: {ext}"],
            )

        diagnose_result = extractor.diagnose(filepath)
        return DiagnosticReport(
            filepath=filepath,
            success=diagnose_result["success"],
            title=diagnose_result.get("title"),
            artist=diagnose_result.get("artist"),
            album=diagnose_result.get("album"),
            duration=diagnose_result.get("duration", 0.0),
            has_cover_art=diagnose_result.get("has_cover_art", False),
            picture_count=diagnose_result.get("picture_count", 0),
            pictures=diagnose_result.get("pictures", []),
            errors=diagnose_result.get("errors", []),
            warnings=diagnose_result.get("warnings", []),
            diagnostics=diagnose_result.get("diagnostics", {}),
        )

    def analyze_directory(
        self,
        directory: str,
        recursive: bool = True,
        include_without_cover: bool = False,
    ) -> tuple[List[DiagnosticReport], DirectorySummary]:
        """
        Analyze all audio files in a directory.

        Args:
            directory: Path to the directory
            recursive: Whether to search recursively
            include_without_cover: Include files without cover art in report list

        Returns:
            Tuple of (list of reports, summary)
        """
        reports = []
        summary = DirectorySummary()

        directory_path = Path(directory)
        if not directory_path.exists():
            summary.all_errors.append(f"Directory not found: {directory}")
            return reports, summary

        # Find all audio files
        if recursive:
            audio_files = []
            for ext in self.SUPPORTED_EXTENSIONS:
                audio_files.extend(directory_path.rglob(f"*{ext}"))
        else:
            audio_files = []
            for ext in self.SUPPORTED_EXTENSIONS:
                audio_files.extend(directory_path.glob(f"*{ext}"))

        # Analyze each file
        for filepath in sorted(audio_files):
            report = self.analyze_file(str(filepath))
            summary.total_files += 1

            ext = filepath.suffix.lower()
            summary.files_by_extension[ext] = summary.files_by_extension.get(ext, 0) + 1

            if report.success:
                summary.successful_extractions += 1
            else:
                summary.files_with_errors += 1

            if report.has_cover_art:
                summary.files_with_cover_art += 1
            else:
                summary.files_without_cover_art += 1

            summary.all_errors.extend(report.errors)
            summary.all_warnings.extend(report.warnings)

            if include_without_cover or report.has_cover_art:
                reports.append(report)

        return reports, summary

    def find_files_without_cover(
        self,
        directory: str,
        recursive: bool = True,
    ) -> List[str]:
        """
        Find all audio files without cover art in a directory.

        Args:
            directory: Path to the directory
            recursive: Whether to search recursively

        Returns:
            List of file paths without cover art
        """
        reports, _ = self.analyze_directory(directory, recursive)
        return [r.filepath for r in reports if not r.has_cover_art]
