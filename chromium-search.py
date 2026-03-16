#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""CLI for Chromium Code Search."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any, TextIO

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class MatchRange:
    start: int
    end: int


@dataclass
class SnippetLine:
    line_text: str
    line_number: int
    ranges: list[MatchRange] = field(default_factory=list)


@dataclass
class Snippet:
    lines: list[SnippetLine] = field(default_factory=list)


@dataclass
class FileResult:
    path: str
    snippets: list[Snippet] = field(default_factory=list)


@dataclass
class SearchResult:
    files: list[FileResult] = field(default_factory=list)
    estimated_result_count: str = "0"
    next_page_token: str = ""


# ---------------------------------------------------------------------------
# Multipart request builder
# ---------------------------------------------------------------------------

DEFAULT_API_KEY = "AIzaSyCqPSptx9mClE5NU4cpfzr6cgdO_phV1lM"
BASE_API_URL = "https://grimoireoss-pa.clients6.google.com"


def random_id() -> str:
    raw = secrets.token_bytes(9)
    out = ""
    for b in raw:
        out += _base36(b)
    return out[:12]


def _base36(n: int) -> str:
    if n == 0:
        return "0"
    chars = ""
    while n:
        n, r = divmod(n, 36)
        chars += "0123456789abcdefghijklmnopqrstuvwxyz"[r]
    return chars


def build_boundary() -> str:
    return f"batch{int(time.time() * 1000)}{random_id()}"


def build_payload(
    query: str,
    page_size: int = 100,
    page_token: str = "",
    context_lines: int = 1,
) -> dict[str, Any]:
    return {
        "queryString": query,
        "searchOptions": {
            "enableDiagnostics": False,
            "exhaustive": False,
            "numberOfContextLines": 1,
            "pageSize": min(page_size, 100),
            "pageToken": page_token,
            "pathPrefix": "",
            "repositoryScope": {
                "root": {
                    "ossProject": "chromium",
                    "repositoryName": "chromium/src",
                },
            },
            "retrieveMultibranchResults": True,
            "savedQuery": "",
            "scoringModel": "",
            "showPersonalizedResults": False,
            "suppressGitLegacyResults": False,
        },
        "snippetOptions": {
            "numberOfContextLines": context_lines,
            "minSnippetLinesPerFile": max(2 * context_lines + 10, 10),
            "minSnippetLinesPerPage": max(2 * context_lines + 20, 60),
        },
    }


def build_request(
    boundary: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    path: str = "/v1/contents/search",
) -> tuple[str, str]:
    url = f"{BASE_API_URL}/batch?%24ct=multipart%2Fmixed%3B%20boundary%3D{boundary}"
    body = "\r\n".join(
        [
            f"--{boundary}",
            "Content-Type: application/http",
            f"Content-ID: <response-{boundary}+gapiRequest@googleapis.com>",
            "",
            f"POST {path}?alt=json&key={api_key}",
            f"sessionid: {random_id()}",
            f"actionid: {random_id()}",
            "X-JavaScript-User-Agent: google-api-javascript-client/1.1.0",
            "X-Requested-With: XMLHttpRequest",
            "Content-Type: application/json",
            "X-Goog-Encode-Response-If-Executable: base64",
            "",
            json.dumps(payload),
            f"--{boundary}--",
            "",
        ]
    )
    return url, body


def extract_json(response_text: str) -> Any:
    m = re.search(r"\{[\s\S]*\}", response_text)
    if not m:
        raise RuntimeError("Could not parse API response: no JSON found")
    return json.loads(m.group(0))


# ---------------------------------------------------------------------------
# gRPC-Web transport (File Service)
# ---------------------------------------------------------------------------


def build_source_root(ref: str = "refs/heads/main") -> list[Any]:
    return [
        [None, "chromium/src", None, None, "chromium"],
        None,
        ref,
        ref,
    ]


def fetch_grpc_web(
    api_key: str,
    body: list[Any],
    timeout: float,
    *,
    service: str = "devtools.grimoire.FileService",
    method: str = "GetContentsStreaming",
) -> Any:
    headers_str = (
        f"X-Goog-Api-Key:{api_key}\n"
        "Content-Type:application/json+protobuf\n"
        "X-User-Agent:grpc-web-javascript/0.1"
    )
    encoded_headers = urllib.parse.quote(headers_str, safe="")
    url = f"{BASE_API_URL}/$rpc/{service}/{method}?$httpHeaders={encoded_headers}"

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": "https://source.chromium.org",
            "Referer": "https://source.chromium.org/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"API request failed: {resp.status}")
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Suggest client
# ---------------------------------------------------------------------------


def build_suggest_payload(
    query: str,
    max_suggestions: int = 10,
) -> dict[str, Any]:
    return {
        "queryString": query,
        "suggestOptions": {
            "enableDiagnostics": False,
            "maxSuggestions": max_suggestions,
            "pathPrefix": "",
            "repositoryScope": {
                "root": {
                    "ossProject": "chromium",
                    "repositoryName": "chromium/src",
                },
            },
            "retrieveMultibranchResults": True,
            "savedQuery": "",
            "showPersonalizedResults": False,
            "suppressGitLegacyResults": False,
        },
    }


def fetch_suggest(
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> list[str]:
    boundary = build_boundary()
    url, body = build_request(boundary, api_key, payload, path="/v1/contents/suggest")
    req = urllib.request.Request(
        url,
        data=body.encode(),
        headers={
            "Content-Type": "text/plain; charset=UTF-8",
            "Origin": "https://source.chromium.org",
            "Referer": "https://source.chromium.org/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"API request failed: {resp.status}")
        text = resp.read().decode()
    raw = extract_json(text)
    return [
        s["fileSpec"]["path"]
        for s in raw.get("suggestions", [])
        if "fileSpec" in s and "path" in s["fileSpec"]
    ]


# ---------------------------------------------------------------------------
# File contents client
# ---------------------------------------------------------------------------


def fetch_file_contents(
    path: str,
    ref: str = "refs/heads/main",
    api_key: str | None = None,
    timeout: float = 15.0,
) -> list[str]:
    key = api_key or os.environ.get("CR_SEARCH_API_KEY", DEFAULT_API_KEY)
    body: list[Any] = [
        [build_source_root(ref), path],
        1,
        None,
        1,
        None,
        None,
        None,
        None,
        1,
    ]
    try:
        response = fetch_grpc_web(key, body, timeout)
    except Exception as exc:
        raise RuntimeError(f"File not found: {path} at {ref}") from exc
    try:
        content = response[0][0][1][2]
    except (IndexError, TypeError) as exc:
        raise RuntimeError(f"No content returned for {path} at {ref}") from exc
    if not isinstance(content, str):
        raise RuntimeError(f"No content returned for {path} at {ref}")
    return content.split("\n")


# ---------------------------------------------------------------------------
# Search client
# ---------------------------------------------------------------------------


def parse_response(raw: dict[str, Any]) -> SearchResult:
    files: list[FileResult] = []
    for sr in raw.get("searchResults", []):
        fsr = sr.get("fileSearchResult")
        if not fsr:
            continue
        snippets: list[Snippet] = []
        for raw_snippet in fsr.get("snippets", []):
            lines: list[SnippetLine] = []
            for rl in raw_snippet.get("snippetLines", []):
                ranges = [
                    MatchRange(start=r.get("start", 0), end=r.get("end", 0))
                    for r in rl.get("ranges", [])
                ]
                lines.append(
                    SnippetLine(
                        line_text=rl.get("lineText", ""),
                        line_number=int(rl.get("lineNumber", "0")),
                        ranges=ranges,
                    )
                )
            snippets.append(Snippet(lines=lines))
        files.append(FileResult(path=fsr["fileSpec"]["path"], snippets=snippets))
    return SearchResult(
        files=files,
        estimated_result_count=raw.get("estimatedResultCount", "0"),
        next_page_token=raw.get("nextPageToken", ""),
    )


def fetch_search(
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> SearchResult:
    boundary = build_boundary()
    url, body = build_request(boundary, api_key, payload)
    req = urllib.request.Request(
        url,
        data=body.encode(),
        headers={
            "Content-Type": "text/plain; charset=UTF-8",
            "Origin": "https://source.chromium.org",
            "Referer": "https://source.chromium.org/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"API request failed: {resp.status} {resp.reason}")
        text = resp.read().decode()
    raw = extract_json(text)
    return parse_response(raw)


def search_all(
    query: str,
    limit: int = 25,
    context_lines: int = 1,
    api_key: str | None = None,
    timeout: float = 15.0,
) -> Generator[SearchResult, None, None]:
    key = api_key or os.environ.get("CR_SEARCH_API_KEY", DEFAULT_API_KEY)
    page_token = ""
    match_count = 0

    while match_count < limit:
        payload = build_payload(
            query,
            page_size=100,
            page_token=page_token,
            context_lines=context_lines,
        )
        result = fetch_search(key, payload, timeout)
        yield result

        for f in result.files:
            for s in f.snippets:
                for ln in s.lines:
                    if ln.ranges:
                        match_count += 1

        if not result.next_page_token or not result.files:
            break
        page_token = result.next_page_token


# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------

_force_no_color = False


def set_no_color(value: bool) -> None:
    global _force_no_color
    _force_no_color = value


def colors_enabled() -> bool:
    return _is_tty() and "NO_COLOR" not in os.environ and not _force_no_color


def _is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_ANSI: dict[str, str] = {
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


def style(text: str, *styles: str) -> str:
    if not colors_enabled():
        return text
    prefix = "".join(_ANSI.get(s, "") for s in styles)
    return f"{prefix}{text}{_ANSI['reset']}" if prefix else text


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------

BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    def __init__(self, message: str, stream: TextIO = sys.stderr) -> None:
        self._message = message
        self._stream = stream
        self._active = False
        self._thread: threading.Thread | None = None

    def start(self) -> Spinner:
        if not (hasattr(self._stream, "isatty") and self._stream.isatty()):
            return self
        self._active = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def _spin(self) -> None:
        i = 0
        while self._active:
            self._stream.write(f"\r{BRAILLE[i % len(BRAILLE)]} {self._message}")
            self._stream.flush()
            i += 1
            time.sleep(0.08)

    def stop(self) -> None:
        self._active = False
        if self._thread:
            self._thread.join()
        if hasattr(self._stream, "isatty") and self._stream.isatty():
            self._stream.write("\r\033[2K")
            self._stream.flush()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

BASE_URL = "https://source.chromium.org/chromium/chromium/src/+/main:"


def line_url(path: str, line: int) -> str:
    return f"{BASE_URL}{path};l={line}"


def highlight_line(line: SnippetLine) -> str:
    if not colors_enabled() or not line.ranges:
        return line.line_text
    result = ""
    pos = 0
    for r in line.ranges:
        result += line.line_text[pos : r.start]
        result += style(line.line_text[r.start : r.end], "bold", "red")
        pos = r.end
    result += line.line_text[pos:]
    return result


def count_matches(results: list[SearchResult]) -> int:
    count = 0
    for r in results:
        for f in r.files:
            for s in f.snippets:
                count += sum(1 for ln in s.lines if ln.ranges)
    return count


def format_grouped(
    results: list[SearchResult],
    context: bool,
    limit: int,
) -> str:
    lines: list[str] = []
    match_count = 0

    for result in results:
        for file in result.files:
            file_lines: list[str] = []
            file_has_output = False
            prev_snippet_end = -1

            for snippet in file.snippets:
                has_match = any(ln.ranges for ln in snippet.lines)
                if not has_match:
                    continue

                if (
                    prev_snippet_end >= 0
                    and snippet.lines
                    and snippet.lines[0].line_number > prev_snippet_end + 1
                ):
                    file_lines.append(style("    ...", "dim"))

                for ln in snippet.lines:
                    if ln.ranges:
                        if match_count >= limit:
                            break
                        match_count += 1
                        num = style(str(ln.line_number).rjust(5), "dim")
                        file_lines.append(f"{num}:  {highlight_line(ln)}")
                        file_has_output = True
                    elif context:
                        num = style(str(ln.line_number).rjust(5), "dim")
                        file_lines.append(style(f"{num}   {ln.line_text}", "dim"))

                if snippet.lines:
                    prev_snippet_end = snippet.lines[-1].line_number

                if match_count >= limit:
                    break

            if file_has_output:
                lines.append(style(file.path, "bold", "cyan"))
                lines.extend(file_lines)
                lines.append("")

            if match_count >= limit:
                break
        if match_count >= limit:
            break

    return "\n".join(lines)


def format_flat(
    results: list[SearchResult],
    context: bool,
    limit: int,
) -> str:
    lines: list[str] = []
    match_count = 0

    for result in results:
        for file in result.files:
            for snippet in file.snippets:
                has_match = any(ln.ranges for ln in snippet.lines)
                if not has_match:
                    continue

                for ln in snippet.lines:
                    if ln.ranges:
                        if match_count >= limit:
                            break
                        match_count += 1
                        lines.append(f"{file.path}:{ln.line_number}: {ln.line_text}")
                    elif context:
                        lines.append(f"{file.path}:{ln.line_number}- {ln.line_text}")
                if context and match_count < limit:
                    lines.append("--")

                if match_count >= limit:
                    break
            if match_count >= limit:
                break
        if match_count >= limit:
            break

    if context and lines and lines[-1] == "--":
        lines.pop()

    return "\n".join(lines)


JsonField = str  # one of: path, line, snippet, context, matchRanges, url


def format_json(
    results: list[SearchResult],
    fields: list[JsonField],
    limit: int,
) -> str:
    wants_context = "context" in fields
    entries: list[dict[str, Any]] = []
    match_count = 0

    for result in results:
        for file in result.files:
            if wants_context:
                for snippet in file.snippets:
                    match_lines = [ln for ln in snippet.lines if ln.ranges]
                    if not match_lines:
                        continue
                    if match_count >= limit:
                        break
                    match_count += len(match_lines)

                    entry: dict[str, Any] = {}
                    primary = match_lines[0]
                    for f in fields:
                        if f == "path":
                            entry["path"] = file.path
                        elif f == "line":
                            entry["line"] = primary.line_number
                        elif f == "snippet":
                            entry["snippet"] = primary.line_text
                        elif f == "context":
                            entry["context"] = [ln.line_text for ln in snippet.lines]
                        elif f == "matchRanges":
                            entry["matchRanges"] = [
                                {"start": r.start, "end": r.end} for r in primary.ranges
                            ]
                        elif f == "url":
                            entry["url"] = line_url(file.path, primary.line_number)
                    entries.append(entry)

                    if match_count >= limit:
                        break
            else:
                for snippet in file.snippets:
                    for ln in snippet.lines:
                        if not ln.ranges:
                            continue
                        if match_count >= limit:
                            break
                        match_count += 1

                        entry = {}
                        for f in fields:
                            if f == "path":
                                entry["path"] = file.path
                            elif f == "line":
                                entry["line"] = ln.line_number
                            elif f == "snippet":
                                entry["snippet"] = ln.line_text
                            elif f == "matchRanges":
                                entry["matchRanges"] = [
                                    {"start": r.start, "end": r.end} for r in ln.ranges
                                ]
                            elif f == "url":
                                entry["url"] = line_url(file.path, ln.line_number)
                        entries.append(entry)
                    if match_count >= limit:
                        break
            if match_count >= limit:
                break
        if match_count >= limit:
            break

    return json.dumps(entries, indent=2)


def summary_line(results: list[SearchResult], limit: int) -> str:
    total = count_matches(results)
    if total == 0:
        return ""

    estimated = results[0].estimated_result_count if results else "0"
    est = int(estimated)
    shown = min(total, limit)

    if est > total:
        return f"Showing {shown} of ~{est:,} results"
    if total > limit:
        return f"Showing {shown} of {total} results"
    return f"Showing {shown} results"


# ---------------------------------------------------------------------------
# Syntax reference
# ---------------------------------------------------------------------------

SYNTAX_REFERENCE = """\
Chromium Code Search — Query Syntax Reference

FILTERS
  case:yes              Case-sensitive search (default: case-insensitive)
  class:<name>          Search for class definitions
  comment:<text>        Search within comments only
  content:<text>        Search within file contents only (exclude file paths)
  file:<pattern>        Filter by file path (supports wildcards: file:*.cc)
  function:<name>       Search for function definitions
  lang:<language>       Filter by programming language
  pcre:<pattern>        Use PCRE regex syntax for search
  symbol:<name>         Search for symbol definitions
  usage:<name>          Search for usages of a symbol

LANG VALUES
  c                     C source files
  cc, c++, cpp          C++ source files
  css                   CSS stylesheets
  go, golang            Go source files
  gn                    GN build files
  html                  HTML files
  java                  Java source files
  javascript, js        JavaScript files
  json                  JSON files
  kotlin                Kotlin source files
  markdown, md          Markdown files
  mojom                 Mojo interface definitions
  objective-c, objc     Objective-C source files
  proto, protobuf       Protocol Buffer definitions
  python, py            Python source files
  rust, rs              Rust source files
  shell, sh, bash       Shell scripts
  sql                   SQL files
  swift                 Swift source files
  textproto, textpb     Text-format Protocol Buffers
  typescript, ts        TypeScript files
  xml                   XML files
  yaml, yml             YAML files

OPERATORS
  AND                   Both terms must match (default for space-separated terms)
  OR                    Either term may match

ADDITIONAL SYNTAX
  "exact phrase"        Match an exact phrase
  -term                 Exclude results matching term
  -filter:value         Negate a filter (e.g., -file:test -lang:java)
  (a OR b) c            Group expressions with parentheses
  \\special              Escape special characters

EXAMPLES
  base::span                              Simple search
  lang:cpp case:yes base::span            Case-sensitive C++ search
  file:*_test.cc base::span               Search only in test files
  lang:cpp -file:test base::span          C++ files, exclude tests
  class:TabStrip                          Find class definitions
  function:AddTabAt lang:cpp              Find function definitions in C++
  "base::span<uint8_t>"                   Exact phrase search
  symbol:kMaxTabs                         Find symbol definitions
  usage:TabStrip                          Find usages of a symbol
  (AddTab OR RemoveTab) lang:cpp          Grouped OR query
"""


# ---------------------------------------------------------------------------
# Search command
# ---------------------------------------------------------------------------


def run_search(
    query: str,
    *,
    limit: int = 30,
    context_lines: int = 0,
    json_fields: str | None = None,
    no_color: bool = False,
) -> None:
    if no_color:
        set_no_color(True)

    api_context = max(context_lines, 1)
    spinner = Spinner("Searching...").start()
    results: list[SearchResult] = []

    try:
        for page in search_all(query, limit=limit, context_lines=api_context):
            results.append(page)
    finally:
        spinner.stop()

    has_results = any(r.files for r in results)
    if not has_results:
        if json_fields is not None:
            sys.stdout.write("[]\n")
        sys.stderr.write("No results found\n")
        return

    if json_fields is not None:
        fields = [f.strip() for f in json_fields.split(",") if f.strip()]
        default_fields: list[JsonField] = ["path", "line", "snippet", "url"]
        sys.stdout.write(
            format_json(results, fields if fields else default_fields, limit) + "\n"
        )
    elif _is_tty():
        summary = summary_line(results, limit)
        if summary:
            sys.stderr.write(summary + "\n\n")
        sys.stdout.write(format_grouped(results, context_lines > 0, limit) + "\n")
    else:
        sys.stdout.write(format_flat(results, context_lines > 0, limit) + "\n")


# ---------------------------------------------------------------------------
# Find command
# ---------------------------------------------------------------------------


def run_find(query: str, *, no_color: bool = False) -> None:
    if no_color:
        set_no_color(True)
    key = os.environ.get("CR_SEARCH_API_KEY", DEFAULT_API_KEY)
    spinner = Spinner("Finding...").start()
    try:
        payload = build_suggest_payload(query)
        paths = fetch_suggest(key, payload, timeout=15.0)
    finally:
        spinner.stop()
    if not paths:
        sys.stderr.write("No results found\n")
        return
    for p in paths:
        sys.stdout.write(p + "\n")


# ---------------------------------------------------------------------------
# Cat command
# ---------------------------------------------------------------------------


def run_cat(
    path: str,
    *,
    ref: str = "refs/heads/main",
    number_lines: bool = False,
) -> None:
    spinner = Spinner("Fetching...").start()
    try:
        lines = fetch_file_contents(path, ref=ref)
    finally:
        spinner.stop()
    for i, line in enumerate(lines, 1):
        if number_lines:
            sys.stdout.write(f"{i:6}\t{line}\n")
        else:
            sys.stdout.write(line + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


USAGE = """\
Usage: chromium-search [command] <query> [flags]

Commands:
  search <query>   Search Chromium source code
  find <name>      Find files by name
  cat <path>       Print file contents
  syntax           Print query syntax reference
  <query>          Implicit search (no subcommand needed)

Flags (search):
  -L, --limit <n>         Max results (default: 30)
  -C, --context <n>       Context lines around matches (default: 0)
      --json [fields]     JSON output (fields: path,line,snippet,context,url)

Flags (cat):
      --ref <ref>         Git ref (default: refs/heads/main)
  -n                      Number output lines

Flags (all):
      --no-color          Disable colored output
  -h, --help              Show this help

Examples:
  chromium-search base::span
  chromium-search 'lang:cpp class:WebContents'
  chromium-search 'usage:TabStripModel -file:out/' -C 3
  chromium-search 'file:*_test.cc base::span' -L 10
  chromium-search 'function:CreateForTesting lang:cpp' --json
  chromium-search find web_contents.h
  chromium-search cat content/public/browser/web_contents.h
  chromium-search cat chrome/browser/BUILD.gn --ref refs/tags/144.0.7559.98
  chromium-search cat base/containers/span.h -n
  chromium-search syntax
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="chromium-search",
        description="Search Chromium source code",
        add_help=False,
    )
    parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument(
        "-L", "--limit", type=int, default=30, help="Max results (default: 30)"
    )
    parser.add_argument(
        "-C",
        "--context",
        type=int,
        default=0,
        metavar="N",
        help="Context lines around matches (default: 0)",
    )
    parser.add_argument(
        "--json",
        nargs="?",
        const="",
        default=None,
        dest="json_fields",
        metavar="fields",
        help="JSON output (fields: path,line,snippet,context,matchRanges,url)",
    )
    parser.add_argument(
        "--ref", default="refs/heads/main", help="Git ref (default: refs/heads/main)"
    )
    parser.add_argument(
        "-n", "--number", action="store_true", help="Number output lines"
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable colored output"
    )
    parser.add_argument("-h", "--help", action="store_true", help="Show this help")
    opts = parser.parse_args()

    if opts.help:
        sys.stderr.write(USAGE)
        return

    positionals: list[str] = opts.args
    subcommand = positionals[0] if positionals else ""

    if subcommand == "syntax":
        sys.stdout.write(SYNTAX_REFERENCE)
        return

    if subcommand == "cat":
        path = " ".join(positionals[1:])
        if not path:
            sys.stderr.write("Usage: chromium-search cat <path> [--ref <ref>] [-n]\n")
            sys.exit(1)
        run_cat(path, ref=opts.ref, number_lines=opts.number)
        return

    if subcommand == "find":
        query = " ".join(positionals[1:])
        if not query:
            sys.stderr.write("Usage: chromium-search find <name>\n")
            sys.exit(1)
        run_find(query, no_color=opts.no_color)
        return

    if subcommand == "search":
        query = " ".join(positionals[1:])
    else:
        query = " ".join(positionals)

    if not query:
        sys.stderr.write(USAGE)
        sys.exit(1)

    run_search(
        query,
        limit=opts.limit,
        context_lines=opts.context,
        json_fields=opts.json_fields,
        no_color=opts.no_color,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)
