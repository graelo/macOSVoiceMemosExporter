#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import platform
import sqlite3
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from shutil import copyfile
from sqlite3 import Connection, Error
from typing import cast

# Offset between Unix epoch (1970-01-01) and Apple epoch (2001-01-01)
APPLE_EPOCH_OFFSET = 978307200.825232


@dataclass
class Memo:
    """Represents a voice memo with its metadata and paths."""

    date: datetime
    duration: timedelta
    label: str | None
    source_path: Path | None
    dest_path: Path | None

    @classmethod
    def from_row(
        cls,
        row: tuple[float, float, str | None, str | None],
        db_dir: Path,
        export_path: Path,
        date_in_name: bool,
        date_format: str,
    ) -> Memo:
        """Create a Memo from a database row."""
        date = datetime.fromtimestamp(row[0] + APPLE_EPOCH_OFFSET)
        duration = timedelta(seconds=row[1])
        label = (
            row[2].replace("/", "_").replace(":", "_")
            if row[2]
            else None
        )

        rel_path = row[3]
        if rel_path:
            source_path = db_dir / rel_path
            extension = Path(rel_path).suffix
            filename = label + extension if label else Path(rel_path).name
            if date_in_name:
                filename = date.strftime(date_format) + filename
            dest_path = export_path / filename
        else:
            source_path = None
            dest_path = None

        return cls(date, duration, label, source_path, dest_path)

    @property
    def date_str(self) -> str:
        return self.date.strftime("%d.%m.%Y %H:%M:%S")

    @property
    def duration_str(self) -> str:
        return format_duration(self.duration)


def format_duration(td: timedelta) -> str:
    """Format a timedelta as HH:MM:SS.cc string."""
    total_seconds = td.total_seconds()
    hours, remainder = divmod(int(total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    centiseconds = int((total_seconds - int(total_seconds)) * 100)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def truncate_str(s: str, width: int) -> str:
    """Truncate string with ellipsis if longer than width."""
    if len(s) <= width:
        return s
    return "..." + s[-(width - 3) :]


def read_key() -> int:
    """Read a single keypress and return its code."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        new_settings = termios.tcgetattr(fd)
        new_settings[3] = new_settings[3] & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)
        tty.setcbreak(sys.stdin)
        return ord(sys.stdin.read(1))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class Table:
    """ASCII table renderer with Unicode box-drawing characters."""

    def __init__(self, columns: list[tuple[str, int]]) -> None:
        self.columns: list[tuple[str, int]] = columns
        self.widths: list[int] = [w for _, w in columns]
        self.names: list[str] = [n for n, _ in columns]

    def _format_cells(self, cells: list[str], sep: str) -> str:
        """Format cells with given separator."""
        formatted = [f"{cell:{w}}" for cell, w in zip(cells, self.widths)]
        return sep.join(formatted)

    def _horizontal_line(self, left: str, mid: str, right: str) -> str:
        """Create a horizontal line with given corner/junction characters."""
        segments = ["─" * w for w in self.widths]
        return left + "─" + ("─" + mid + "─").join(segments) + "─" + right

    def print_header(self) -> None:
        """Print the table header with column names."""
        print(self._horizontal_line("┌", "┬", "┐"))
        print("│ " + self._format_cells(self.names, " │ ") + " │")
        print(self._horizontal_line("├", "┼", "┤"))

    def print_row(self, cells: list[str], end: str = "\n") -> None:
        """Print a data row."""
        print("│ " + self._format_cells(cells, " │ ") + " │", end=end)

    def print_footer(self) -> None:
        """Print the table footer."""
        print(self._horizontal_line("└", "┴", "┘"))


def create_connection(db_file: Path) -> Connection | None:
    """Create a database connection to the SQLite database."""
    try:
        return sqlite3.connect(db_file)
    except Error as e:
        print(e)
        return None


def get_all_memos(
    conn: Connection, major_version: int
) -> list[tuple[float, float, str | None, str | None]]:
    """Query all memos from the database."""
    cur = conn.cursor()
    # Sonoma (14+) uses ZCUSTOMLABELFORSORTING, earlier uses ZCUSTOMLABEL
    label_column = "ZCUSTOMLABELFORSORTING" if major_version >= 14 else "ZCUSTOMLABEL"
    cur.execute(
        f"SELECT ZDATE, ZDURATION, {label_column}, ZPATH FROM ZCLOUDRECORDING ORDER BY ZDATE"
    )
    return cur.fetchall()


def process_memos(
    memos: list[Memo],
    table: Table,
    export_all: bool,
) -> None:
    """Process and optionally export each memo with user interaction."""
    old_path_width = table.widths[2]
    new_path_width = table.widths[3]

    for memo in memos:
        old_path_short = truncate_str(
            memo.source_path.name if memo.source_path else "", old_path_width
        )
        new_path_short = truncate_str(
            str(memo.dest_path) if memo.dest_path else "", new_path_width
        )

        row_data = [
            memo.date_str,
            memo.duration_str,
            old_path_short,
            new_path_short,
        ]

        if not memo.source_path:
            table.print_row(row_data + ["No File"])
            continue

        if export_all:
            key = 10  # Enter
        else:
            table.print_row(row_data + ["Export?"], end="\r")
            key = 0
            while key not in (10, 27):
                key = read_key()

        assert memo.source_path is not None and memo.dest_path is not None
        match key:
            case 10:  # Enter - export
                copyfile(memo.source_path, memo.dest_path)
                mod_time = time.mktime(memo.date.timetuple())
                os.utime(memo.dest_path, (mod_time, mod_time))
                table.print_row(row_data + ["Exported!"])
            case 27:  # Escape - skip
                table.print_row(row_data + ["Skipped"])


def main() -> None:
    # Detect macOS version
    mac_version = platform.mac_ver()[0]
    major_version = int(mac_version.split(".")[0]) if mac_version else 0

    # Define default paths (different for macOS Sonoma 14+ vs earlier)
    if major_version >= 14:
        db_path_default = (
            Path.home()
            / "Library"
            / "Group Containers"
            / "group.com.apple.VoiceMemos.shared"
            / "Recordings"
            / "CloudRecordings.db"
        )
    else:
        db_path_default = (
            Path.home()
            / "Library"
            / "Application Support"
            / "com.apple.voicememos"
            / "Recordings"
            / "CloudRecordings.db"
        )
    export_path_default = Path.home() / "Voice Memos Export"

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Export audio files from macOS Voice Memo App with right filename and date created."
    )
    parser.add_argument(
        "-d",
        "--db-path",
        type=Path,
        help="path to Voice Memos database",
        default=db_path_default,
    )
    parser.add_argument(
        "-e",
        "--export-path",
        type=Path,
        help="folder for exported files",
        default=export_path_default,
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="export all memos without prompting",
    )
    parser.add_argument(
        "--date-in-name",
        action="store_true",
        help="include recording date in filename",
    )
    parser.add_argument(
        "--date-in-name-format",
        type=str,
        default="%Y-%m-%d-%H-%M-%S_",
        help="date format for filename (default: %(default)s)",
    )
    parser.add_argument(
        "--no-finder",
        action="store_true",
        help="don't open Finder after export",
    )
    args = parser.parse_args()

    db_path = cast(Path, args.db_path).expanduser().resolve()
    export_path = cast(Path, args.export_path).expanduser().resolve()
    export_all = cast(bool, args.all)
    date_in_name = cast(bool, args.date_in_name)
    date_in_name_format = cast(str, args.date_in_name_format)
    no_finder = cast(bool, args.no_finder)

    # Check database access
    if not os.access(db_path, os.R_OK):
        print(f"No permission to read database file: {db_path}")
        print()
        print("This script requires Full Disk Access.")
        print("Go to System Settings > Privacy & Security > Full Disk Access")
        print("and add your terminal application.")
        print()
        print("Alternatively, copy the entire Recordings folder to a temporary")
        print("location and run this tool with --db-path pointing to the copy.")
        exit(1)

    # Load memos from database
    conn = create_connection(db_path)
    if not conn:
        exit(1)
    with conn:
        rows = get_all_memos(conn, major_version)
    if not rows:
        print("No memos found.")
        exit(0)

    # Convert rows to Memo objects
    memos = [
        Memo.from_row(row, db_path.parent, export_path, date_in_name, date_in_name_format)
        for row in rows
    ]

    # Create export folder
    export_path.mkdir(exist_ok=True)

    # Set up table
    table = Table([
        ("Date", 19),
        ("Duration", 11),
        ("Old Path", 32),
        ("New Path", 60),
        ("Status", 12),
    ])

    # Print instructions and header
    print()
    if not export_all:
        print("Press ENTER to export, ESC to skip.")
        print()
    table.print_header()

    # Process memos
    process_memos(memos, table, export_all)

    # Print footer and summary
    table.print_footer()
    print()
    print(f"Done. Memos exported to: {export_path}")
    print()

    # Open Finder if requested
    if not no_finder:
        subprocess.Popen(["open", export_path])


if __name__ == "__main__":
    main()
