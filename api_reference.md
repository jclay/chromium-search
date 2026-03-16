# Chromium Code Search API Reference

The Chromium Code Search UI at `source.chromium.org` is powered by the Grimoire API, a Google-internal service exposed at `grimoireoss-pa.clients6.google.com`. This document describes the API endpoints, request/response formats, and known limitations discovered through reverse engineering.

## Table of Contents

- [Authentication & Common Config](#authentication--common-config)
- [Transport Formats](#transport-formats)
  - [Batch (REST) API](#batch-rest-api)
  - [gRPC-Web API](#grpc-web-api)
- [Endpoints](#endpoints)
  - [Content Search](#1-content-search) - text search across the codebase
  - [Suggest](#2-suggest) - file name / symbol autocomplete
  - [File Service (GetContentsStreaming)](#3-file-service-getcontentsstreaming) - file content & directory listing
  - [History](#4-history) - git log
  - [Project Info](#5-project-info) - repository metadata
- [Data Types](#data-types)
- [Ref/Tag Support Summary](#reftag-support-summary)
- [Context Lines (`-C N`)](#context-lines--c-n)
- [Strategies for CLI Commands](#strategies-for-cli-commands)

---

## Authentication & Common Config

No user authentication is required. All requests use a public API key.

```
API_KEY = "AIzaSyCqPSptx9mClE5NU4cpfzr6cgdO_phV1lM"
BASE_URL = "https://grimoireoss-pa.clients6.google.com"
```

**Required headers for all requests:**

```
Origin: https://source.chromium.org
Referer: https://source.chromium.org/
```

CORS is enforced; requests must originate from (or spoof) `source.chromium.org`.

---

## Transport Formats

The API uses two distinct transport formats depending on the endpoint.

### Batch (REST) API

Used by: Search, Suggest, History, Project Info.

Requests are wrapped in a multipart batch envelope. Each batch can contain one logical HTTP request.

**URL:** `POST {BASE_URL}/batch?$ct=multipart/mixed; boundary={boundary}`

**Content-Type:** `text/plain; charset=UTF-8`

**Request body template:**

```
--{boundary}\r\n
Content-Type: application/http\r\n
Content-Transfer-Encoding: binary\r\n
Content-ID: <{boundary}+gapiRequest@googleapis.com>\r\n
\r\n
{METHOD} {path}?alt=json&key={API_KEY}\r\n
sessionid: {random_alphanumeric_10}\r\n
actionid: {random_alphanumeric_10}\r\n
X-JavaScript-User-Agent: google-api-javascript-client/1.1.0\r\n
X-Requested-With: XMLHttpRequest\r\n
Content-Type: application/json\r\n
X-Goog-Encode-Response-If-Executable: base64\r\n
\r\n
{JSON payload}\r\n
--{boundary}--\r\n
```

**Boundary format:** `batch{timestamp}{random_digits}` (e.g. `batch1419008156730348154`)

**Response:** Multipart response with the same boundary format. The JSON payload is embedded after the HTTP status line and headers within the part.

### gRPC-Web API

Used by: File Service (GetContentsStreaming), Decorations Service.

**URL:** `POST {BASE_URL}/$rpc/{service}/{method}?$httpHeaders={encoded_headers}`

The `$httpHeaders` query parameter contains URL-encoded header pairs:

```
X-Goog-Api-Key:{API_KEY}
Content-Type:application/json+protobuf
X-User-Agent:grpc-web-javascript/0.1
```

**Request Content-Type:** `application/x-www-form-urlencoded;charset=UTF-8`

**Request body:** JSON array (positional protobuf encoding). Fields are identified by position, not name.

**Response Content-Type:** `application/json+protobuf; charset=UTF-8`

**Response body:** JSON array (positional protobuf encoding).

---

## Endpoints

### 1. Content Search

Full-text search across indexed source code.

**Transport:** Batch (REST)
**Method:** `POST /v1/contents/search`

#### Request

```json
{
  "queryString": "WebContents",
  "searchOptions": {
    "enableDiagnostics": false,
    "exhaustive": false,
    "isDedupResultsEnabled": false,
    "numberOfContextLines": 1,
    "pageSize": 100,
    "pageToken": "",
    "pathPrefix": "",
    "repositoryScope": {
      "root": {
        "ossProject": "chromium",
        "repositoryName": "chromium/src"
      }
    },
    "retrieveMultibranchResults": true,
    "savedQuery": "",
    "scoringModel": "",
    "showPersonalizedResults": false,
    "suppressGitLegacyResults": false
  },
  "snippetOptions": {
    "minSnippetLinesPerFile": 10,
    "minSnippetLinesPerPage": 60,
    "numberOfContextLines": 1
  }
}
```

#### Request Fields

| Field | Type | Description |
|-------|------|-------------|
| `queryString` | string | Search query. Supports filters like `file:`, `class:`, `function:`, `lang:`, `case:yes`, `pcre:yes`, `symbol:`, `comment:`, `content:`, `usage:`. See [Query Syntax](#query-syntax). |
| `searchOptions.pageSize` | int | Results per page (max 100). |
| `searchOptions.pageToken` | string | Pagination token from previous response's `nextPageToken`. |
| `searchOptions.pathPrefix` | string | Restrict search to files under this path (e.g. `"content/browser/"`). |
| `searchOptions.repositoryScope.root.ossProject` | string | Project name (e.g. `"chromium"`). |
| `searchOptions.repositoryScope.root.repositoryName` | string | Repository name (e.g. `"chromium/src"`). |
| `searchOptions.retrieveMultibranchResults` | bool | **Must be `true`** to get results. Setting to `false` returns empty results. |
| `searchOptions.exhaustive` | bool | When `true`, returns exact total count (slower). |
| `searchOptions.numberOfContextLines` | int | Nominal context lines (no observed effect; use `snippetOptions` instead). |
| `snippetOptions.numberOfContextLines` | int | **The effective context line control.** Lines of context before/after each match. Supports 0-100+. See [Context Lines](#context-lines--c-n). |
| `snippetOptions.minSnippetLinesPerFile` | int | Minimum snippet lines per file. **Must be > 0** or no snippets are returned. |
| `snippetOptions.minSnippetLinesPerPage` | int | Minimum total snippet lines per page. **Must be > 0** or no snippets are returned. |

#### Response

```json
{
  "searchResults": [
    {
      "fileSearchResult": {
        "fileSpec": {
          "sourceRoot": {
            "repositoryKey": {
              "repositoryName": "chromium/src",
              "ossProject": "chromium"
            },
            "refSpec": "refs/heads/main"
          },
          "path": "content/public/browser/web_contents.h",
          "type": "FILE"
        },
        "snippets": [
          {
            "snippetLines": [
              {
                "lineText": "class WebContents : public PageNavigator {",
                "lineNumber": "95",
                "matchingRanges": {
                  "lineNumber": "95",
                  "columnRanges": [
                    { "startIndex": 6, "length": 11 }
                  ]
                },
                "tokens": [
                  { "tokenType": "KEYWORD", "range": { "length": 5 } }
                ]
              }
            ]
          }
        ]
      }
    }
  ],
  "estimatedResultCount": "4391",
  "nextPageToken": "...",
  "exhaustive": false,
  "requestToken": "..."
}
```

#### Query Syntax

| Filter | Aliases | Description | Example |
|--------|---------|-------------|---------|
| `case:yes` | `case:y` | Case-sensitive search | `case:yes Hello` |
| `class:` | | Class name search | `class:WebContents` |
| `comment:` | | Search within comments | `comment:TODO` |
| `content:` | | File contents only (excludes filenames) | `content:hello` |
| `file:` | `filepath:`, `path:`, `f:` | Search by filename/path (regex) | `file:\.mojom$` |
| `function:` | `func:` | Function name search | `function:CreateForTesting` |
| `lang:` | `language:` | Filter by language | `lang:c++ WebContents` |
| `pcre:yes` | | Perl-compatible regex (multiline) | `pcre:yes @Provides\s+double` |
| `symbol:` | | Symbol search | `symbol:kMaxSize` |
| `usage:` | | Excludes comments and string literals | `usage:map` |

Operators: `AND`, `OR`, `-` (exclude), `"..."` (literal), `(...)` (grouping).

#### Limitations

> **The search index only covers the `main` branch.**
>
> There is no way to search at a specific tag, branch, or commit via this API.
> The internal query always resolves to `git:chromium/codesearch/chromium/src@main`.
> All ref-related fields (`refSpec`, `ref`, `revision`, `branch`) added to
> `repositoryScope.root` are silently ignored.

---

### 2. Suggest

Autocomplete / file-finding endpoint. Returns file path suggestions ranked by relevance.

**Transport:** Batch (REST)
**Method:** `POST /v1/contents/suggest`

#### Request

```json
{
  "queryString": "web_contents.h",
  "suggestOptions": {
    "enableDiagnostics": false,
    "maxSuggestions": 7,
    "pathPrefix": "",
    "repositoryScope": {
      "root": {
        "ossProject": "chromium",
        "repositoryName": "chromium/src"
      }
    },
    "retrieveMultibranchResults": true,
    "savedQuery": "",
    "showPersonalizedResults": false,
    "suppressGitLegacyResults": false
  }
}
```

#### Request Fields

| Field | Type | Description |
|-------|------|-------------|
| `queryString` | string | Partial filename or search text. |
| `suggestOptions.maxSuggestions` | int | Maximum number of suggestions (max observed: 10). |
| `suggestOptions.pathPrefix` | string | Restrict suggestions to files under this path (e.g. `"content/"`). Useful for scoped `find`-like behavior. |
| `suggestOptions.repositoryScope` | object | Same as search. Only `ossProject` and `repositoryName` are effective. |

#### Response

```json
{
  "suggestions": [
    {
      "fileSpec": {
        "sourceRoot": {
          "repositoryKey": {
            "repositoryName": "chromium/src",
            "ossProject": "chromium"
          },
          "refSpec": "refs/heads/main"
        },
        "path": "content/public/browser/web_contents.h"
      }
    }
  ]
}
```

#### Limitations

- Results always come from `refs/heads/main`.
- Maximum ~10 suggestions per request.
- Good for finding files by partial name match; not suitable for exhaustive listing.

#### Use Case: `find` Command

The Suggest API is the best option for fuzzy file finding by name. For pattern-based file search (e.g. `find -name "*.mojom"`), use the Content Search API with `file:` filter:

```json
{ "queryString": "file:\\.mojom$" }
```

This returns file paths matching the regex pattern, with `pathPrefix` for directory scoping.

---

### 3. File Service (GetContentsStreaming)

Retrieves file contents or directory listings. **This is the only endpoint that supports arbitrary refs/tags.**

**Transport:** gRPC-Web
**Service:** `devtools.grimoire.FileService`
**Method:** `GetContentsStreaming`

**Full URL:**
```
POST {BASE_URL}/$rpc/devtools.grimoire.FileService/GetContentsStreaming?$httpHeaders={url_encoded_headers}
```

Where `$httpHeaders` is URL-encoded:
```
X-Goog-Api-Key:AIzaSyCqPSptx9mClE5NU4cpfzr6cgdO_phV1lM
Content-Type:application/json+protobuf
X-User-Agent:grpc-web-javascript/0.1
```

#### Request Format

The request body is a JSON array using positional protobuf encoding.

##### For file content or directory listing (full details):

```json
[
  [
    <sourceRoot>,
    "<path>"
  ],
  1,     // includeContent
  null,
  1,     // includeTokens (syntax highlighting data)
  null,
  null,
  null,
  null,
  1      // unknown flag
]
```

##### For tree/sidebar listing (children only, no content):

```json
[
  [
    <sourceRoot>,
    "<path>",
    3
  ]
]
```

#### SourceRoot Structure

```json
[
  [null, "<repositoryName>", null, null, "<ossProject>"],  // repositoryKey
  null,
  "<refSpec>",    // e.g. "refs/tags/144.0.7559.98" or "refs/heads/main"
  "<refSpec>"     // repeated (requested ref = resolved ref)
]
```

**Example (tag):**
```json
[[null,"chromium/src",null,null,"chromium"],null,"refs/tags/144.0.7559.98","refs/tags/144.0.7559.98"]
```

**Example (main branch):**
```json
[[null,"chromium/src",null,null,"chromium"],null,"refs/heads/main","refs/heads/main"]
```

#### Response: Directory Listing

When `<path>` points to a directory, the response contains a listing of all immediate children (files and subdirectories). **All entries are returned in a single response** -- there is no pagination, even for large directories (e.g. `third_party/` with 334 entries).

```json
[
  [
    [
      [
        <entries_array>,
        null,
        ["<edit_url>", "<googlesource_url>"]
      ],
      null,    // index 1
      null,    // index 2
      null,    // index 3
      null,    // index 4
      null,    // index 5
      null,    // index 6
      [1]      // index 7
    ]
  ]
]
```

**Path to entries:** `response[0][0][0][0]`

Each entry in the entries array:

```json
["<full_path>", "<git_hash>", null, null, <type>, null, null, [1]]
```

| Index | Field | Description |
|-------|-------|-------------|
| 0 | `path` | Full path from repository root (e.g. `"content/public/browser/web_contents.h"`) |
| 1 | `hash` | Git blob/tree SHA-1 hash |
| 2 | | Always `null` |
| 3 | | Always `null` |
| 4 | `type` | Entry type (see below) |
| 5 | | Always `null` |
| 6 | | Always `null` |
| 7 | | Always `[1]` |

**Entry types:**

| Value | Meaning | Example |
|-------|---------|---------|
| `1` | File | `web_contents.h` |
| `3` | Directory | `browser/` |
| `5` | Submodule | `v8`, `clank` |
| `6` | Symlink (or special file) | `PRESUBMIT_test.py` (rare) |

#### Response: File Content

When `<path>` points to a file, the response includes the file content and optionally syntax tokens.

```json
[
  [
    [
      [
        ["<path>", "<hash>", null, null, 1, null, null, [1]]
      ],
      null,
      ["<edit_url>", "<googlesource_url>"]
    ],
    [
      "<line1_text>",
      "<line2_text>",
      ...
    ],
    [
      [<tokens_for_line1>],
      [<tokens_for_line2>],
      ...
    ],
    null, null, null, null,
    [1]
  ]
]
```

**Path to file content lines:** `response[0][1]` (array of strings, one per line)
**Path to syntax tokens:** `response[0][2]` (parallel array of token data per line)

#### Directory Listing Example

**Request** -- list `content/public/browser/` at tag `144.0.7559.98`:
```json
[[[[null,"chromium/src",null,null,"chromium"],null,"refs/tags/144.0.7559.98","refs/tags/144.0.7559.98"],"content/public/browser"],1,null,1,null,null,null,null,1]
```

**Response** (abbreviated):
```json
[[[[
  ["content/public/browser/android","7d7ee5f...",null,null,3,null,null,[1]],
  ["content/public/browser/chromeos","b426d68...",null,null,3,null,null,[1]],
  ["content/public/browser/BUILD.gn","2a0f8af...",null,null,1,null,null,[1]],
  ["content/public/browser/web_contents.h","cb31104...",null,null,1,null,null,[1]],
  ...
],null,["https://edit.chromium.org/...","https://chromium.googlesource.com/..."]],null,null,null,null,null,null,[1]]]]
```

---

### 4. History

Git commit history for a file or directory.

**Transport:** Batch (REST)
**Method:** `GET /v1/history/list`

#### Request

Parameters are passed as URL query string (not JSON body):

```
GET /v1/history/list?
  logForPath=true&
  logForPathWithPagination=true&
  maxLogEntries=1&
  path=content/public/browser/web_contents.h&
  repositoryKey.ossProject=chromium&
  repositoryKey.repositoryName=chromium/src&
  starts=refs/tags/144.0.7559.98&
  key={API_KEY}
```

#### Request Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | File or directory path. |
| `repositoryKey.ossProject` | string | Project name. |
| `repositoryKey.repositoryName` | string | Repository name. |
| `starts` | string | **Ref/tag to start from.** Supports any ref (e.g. `refs/tags/144.0.7559.98`, `refs/heads/main`). |
| `maxLogEntries` | int | Maximum number of commits to return. |
| `logForPath` | bool | Whether to log for the specific path. |
| `logForPathWithPagination` | bool | Enable pagination. |

#### Response

```json
{
  "commitLogEntries": [
    {
      "commitId": "5ac7f34e2f3beb343e55e73a970075ca0f232fe4",
      "commitTime": "2025-11-24T21:48:00Z",
      "author": {
        "email": "dsanders11@ucsbalum.com",
        "name": "David Sanders"
      },
      "commitSubject": "Remove some includes of //ui/gfx/geometry/rect{_f}.h",
      "commitMessage": "...",
      "metadata": {
        "Bug": "40318405, 429365675",
        "Change-Id": "I8cc863961b72ea250dfa1b893e06de0c13bae9d6",
        "Reviewed-on": "https://chromium-review.googlesource.com/c/chromium/src/+/7186893",
        "Cr-Commit-Position": "refs/heads/main@{#1549408}"
      },
      "fileDiffEntries": [
        {
          "newPath": "content/public/browser/web_contents.h",
          "oldPath": "content/public/browser/web_contents.h",
          "newHash": "cb311047afdeb839194cdb467f30d53c72f0dbd2",
          "oldHash": "bbce23f1ed1c3b555000cf51f057ec195b9de07d"
        }
      ],
      "parentCommitIds": ["1e97b15b21931a3e33b8635a1e5c350a6a67b57f"],
      "committer": {
        "email": "chromium-scoped@luci-project-accounts.iam.gserviceaccount.com",
        "name": "Chromium LUCI CQ"
      }
    }
  ],
  "pageToken": "1;refs/tags/144.0.7559.98"
}
```

---

### 5. Project Info

Repository metadata and configuration.

**Transport:** Batch (REST)
**Method:** `GET /v1/ossProjects/{projectName}`

#### Request

```
GET /v1/ossProjects/chromium?multibranchEnabled=true&key={API_KEY}
```

#### Response (abbreviated)

```json
{
  "name": "chromium",
  "displayName": "Chromium",
  "repositories": [
    {
      "repository": {
        "repositoryKey": {
          "repositoryName": "codesearch/chromium/src",
          "hostName": "chromium"
        }
      },
      "hasSemanticIndex": true,
      "name": "chromium/src",
      "defaultBranch": "refs/heads/main",
      "language": "C++",
      "license": "BSD 3-clause",
      "lastCommitTime": "2026-03-16T02:54:49Z"
    }
  ]
}
```

Lists all repositories in the project, their default branches, and indexing status.

---

### 6. Decorations Service

Provides semantic annotations (cross-references, symbol types) for a file.

**Transport:** gRPC-Web
**Service:** `devtools.sourcerers.DecorationsService`
**Method:** `ListDecorations`

Not fully documented here as it's primarily used for IDE-like features (go-to-definition, find-references) in the web UI. The request format follows the same gRPC-Web JSON+protobuf pattern as the File Service.

---

## Data Types

### Repository Identifiers

| Field | Value | Description |
|-------|-------|-------------|
| `ossProject` | `"chromium"` | Top-level project |
| `repositoryName` | `"chromium/src"` | Repository within the project |

### Available Repositories (Chromium project)

| Name | Indexed | Default Branch |
|------|---------|----------------|
| `chromium/src` | Yes (semantic) | `refs/heads/main` |
| `infra/infra_superproject` | Yes (semantic) | `refs/heads/main` |
| `build` | Yes (semantic) | `refs/heads/main` |
| `chromium/tools/depot_tools` | Yes (semantic) | `refs/heads/main` |

Several additional repos exist but are hidden (not searchable).

### Ref Formats

| Format | Example |
|--------|---------|
| Branch | `refs/heads/main` |
| Tag | `refs/tags/144.0.7559.98` |

---

## Ref/Tag Support Summary

| Endpoint | Supports Arbitrary Refs? | Notes |
|----------|--------------------------|-------|
| **Content Search** | **No** | Only searches `main`. All ref-related fields silently ignored. |
| **Suggest** | **No** | Only returns results from `main`. |
| **File Service** | **Yes** | Full support for any ref/tag in `sourceRoot`. |
| **History** | **Yes** | Via `starts=` parameter. |
| **Project Info** | N/A | Static metadata. |

---

## Context Lines (`-C N`)

The API fully supports configurable context lines around search matches, equivalent to `grep -C N`.

### Controlling Parameter

**`snippetOptions.numberOfContextLines`** is the parameter that controls context. The identically-named `searchOptions.numberOfContextLines` has no observable effect and can be left at `1`.

```json
{
  "snippetOptions": {
    "numberOfContextLines": 10,
    "minSnippetLinesPerFile": 30,
    "minSnippetLinesPerPage": 100
  }
}
```

### Verified Behavior

Tested with a single-match query (`"class WebContents : public PageNavigator"` matching line 175):

| `numberOfContextLines` | Lines Returned | Range |
|------------------------|---------------|-------|
| 0 | 1 | 175 only |
| 1 | 3 | 174-176 |
| 3 | 7 | 172-178 |
| 5 | 11 | 170-180 |
| 10 | 21 | 165-185 |
| 20 | 41 | 155-195 |
| 50 | 101 | 125-225 |
| 100 | 201 | 75-275 |

Formula: `2 * N + 1` lines per isolated match (N before + match + N after). Adjacent matches merge into a single snippet. No upper limit detected up to at least 100.

### Distinguishing Match Lines from Context Lines

Every line in a snippet has a `matchingRanges` object, but only actual match lines have non-null `columnRanges`:

```json
// Match line (has highlight ranges):
{
  "lineNumber": "175",
  "lineText": "class WebContents : public PageNavigator, ...",
  "matchingRanges": {
    "lineNumber": "175",
    "columnRanges": [{ "startIndex": 0, "length": 40 }]
  }
}

// Context line (columnRanges is null):
{
  "lineNumber": "174",
  "lineText": "// See navigation_controller.h for more details.",
  "matchingRanges": {
    "lineNumber": "174",
    "columnRanges": null
  }
}
```

**Rule:** `line.matchingRanges.columnRanges !== null` means it's a match line.

### `minSnippetLinesPerFile` and `minSnippetLinesPerPage`

These are **minimum thresholds**, not additive.

- **Must be > 0** to receive any snippet data. Setting both to `0` causes the API to return no snippets at all.
- They do **not** add extra lines beyond what `numberOfContextLines` requests. A request with `numberOfContextLines=3` always returns 7 lines per match regardless of whether `minSnippetLinesPerFile` is 7, 50, or 200.
- **Recommended:** Set `minSnippetLinesPerFile` to at least `2 * numberOfContextLines + 10` and `minSnippetLinesPerPage` to at least `2 * numberOfContextLines + 20` to ensure all context is included.

### Implementation

To support `-C N`:

```python
def build_search_payload(query, context_lines=1, page_size=100, path_prefix=""):
    return {
        "queryString": query,
        "searchOptions": {
            "numberOfContextLines": 1,  # doesn't matter, kept for compat
            "pageSize": page_size,
            "pathPrefix": path_prefix,
            "repositoryScope": {
                "root": {"ossProject": "chromium", "repositoryName": "chromium/src"}
            },
            "retrieveMultibranchResults": True,
            # ... other fields ...
        },
        "snippetOptions": {
            "numberOfContextLines": context_lines,  # THIS is the one that matters
            "minSnippetLinesPerFile": max(2 * context_lines + 10, 10),
            "minSnippetLinesPerPage": max(2 * context_lines + 20, 60),
        }
    }
```

---

## Strategies for CLI Commands

### `search` -- Text Search

Use the [Content Search](#1-content-search) endpoint. Supports the full query syntax including `file:`, `lang:`, `class:`, `function:` filters and regex.

```
POST /v1/contents/search
queryString: "WebContents lang:c++"
pathPrefix: "content/"
pageSize: 100
```

**Limitation:** Always searches `main`. To search at a tag, there is no server-side support. You would need to search `main` first, then verify file existence at the tag via the File Service.

### `ls` -- Directory Listing

Use the [File Service](#3-file-service-getcontentsstreaming) with a directory path. Returns all entries in a single response.

```
# Request body for listing content/public/browser/ at tag 144.0.7559.98
[[
  [[null,"chromium/src",null,null,"chromium"],null,"refs/tags/144.0.7559.98","refs/tags/144.0.7559.98"],
  "content/public/browser"
],1,null,1,null,null,null,null,1]
```

Parse `response[0][0][0][0]` for the entries array. Filter by `entry[4]` for type:
- `1` = file
- `3` = directory
- `5` = submodule

Supports any ref/tag. No pagination needed.

### `find` -- File Search by Name

**Option A: Suggest API** (fast, fuzzy, limited to ~10 results)

Best for interactive "find file by name" use cases. Supports `pathPrefix` for directory scoping.

```json
{
  "queryString": "web_contents.h",
  "suggestOptions": {
    "maxSuggestions": 10,
    "pathPrefix": "content/",
    "repositoryScope": { "root": { "ossProject": "chromium", "repositoryName": "chromium/src" } }
  }
}
```

**Option B: Content Search with `file:` filter** (regex, exhaustive, paginated)

Best for pattern-based file search. Returns up to 100 results per page with pagination.

```json
{
  "queryString": "file:\\.mojom$ file:content/",
  "searchOptions": { "pageSize": 100 }
}
```

Supports regex patterns. Can combine with `pathPrefix` in `searchOptions` or `file:` filter in query.

**Option C: Recursive directory walk via File Service** (any ref, exhaustive, slow)

For ref-scoped file finding, recursively list directories via the File Service. Start at the target directory, collect all entries, recurse into subdirectories (type=3), and filter client-side by filename/extension.

```
1. List "content/" -> entries
2. For each entry with type=3, list that subdirectory
3. Filter collected file paths by pattern (e.g. *.mojom)
```

This is the only approach that supports searching at a specific tag, but is O(n) in the number of directories traversed. Can be parallelized.

### `cat` -- File Content

Use the [File Service](#3-file-service-getcontentsstreaming) with a file path.

```
# Request body for content/public/browser/web_contents.h at tag 144.0.7559.98
[[
  [[null,"chromium/src",null,null,"chromium"],null,"refs/tags/144.0.7559.98","refs/tags/144.0.7559.98"],
  "content/public/browser/web_contents.h"
],1,null,1,null,null,null,null,1]
```

File content lines are at `response[0][1]` (array of strings).

### `log` -- Git History

Use the [History](#4-history) endpoint. Supports any ref.

```
GET /v1/history/list?
  path=content/public/browser/web_contents.h&
  repositoryKey.ossProject=chromium&
  repositoryKey.repositoryName=chromium/src&
  starts=refs/tags/144.0.7559.98&
  maxLogEntries=10
```
