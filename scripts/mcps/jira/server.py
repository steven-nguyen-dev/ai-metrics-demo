#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""
Jira Model Context Protocol (MCP) Server
-----------------------------------------
A zero-dependency, universal MCP server providing full Jira issue inspection,
JQL search, attachment downloads, and in-memory text/log streaming for AI agents.

Runs out-of-the-box on Python 3 standard library on any machine (macOS, Linux, Windows).
"""

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SERVER_NAME = "jira-mcp-server"
SERVER_VERSION = "1.0.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Environment and Configuration Loader
# ---------------------------------------------------------------------------

DEFAULT_ENV_TEMPLATE = """# ==============================================================================
# Jira MCP Server Configuration (.env)
# ==============================================================================
# Instructions:
# 1. Copy this file to .env:
#    cp .env.example .env   (or run: python3 server.py --init-env)
# 2. Fill in your Jira credentials below.
# 3. Test your connection:
#    python3 server.py --test
# ==============================================================================

# [Required] Your Jira instance base URL
# Cloud: https://your-domain.atlassian.net
# Server / Data Center: https://jira.yourcompany.com
JIRA_HOST=https://your-domain.atlassian.net

# [Required for Jira Cloud] Your Atlassian login email address
JIRA_EMAIL=your-email@company.com

# [Required for Jira Cloud] Jira API Token
# Generate token at: https://id.atlassian.com/manage-profile/security/api-tokens
JIRA_API_TOKEN=your_jira_api_token_here

# [Alternative for Jira Server / Data Center] Personal Access Token (PAT)
# Uncomment and fill if using Jira Server/Data Center instead of email + API token
# JIRA_PAT=your_personal_access_token_here

# [Optional] Default directory for downloaded attachments (relative to project root)
# Default: .scratchpads/downloads
JIRA_DOWNLOAD_DIR=.scratchpads/downloads

# [Optional] Jira REST API Version
# Default: 3 (Jira Cloud). Set to 2 for Jira Server / Data Center
JIRA_API_VERSION=3
"""

def _find_project_root() -> Path:
    """Locate project root by searching for marker files (.git, .cursor, .mcp.json, etc.)."""
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / ".git").exists() or (p / ".cursor").is_dir() or (p / ".mcp.json").is_file():
            return p
    script_dir = Path(__file__).resolve().parent
    for p in [script_dir, *script_dir.parents]:
        if (p / ".git").exists() or (p / ".cursor").is_dir() or (p / ".mcp.json").is_file():
            return p
    return script_dir.parent.parent if script_dir.parent.parent.exists() else script_dir


def _load_env_file(filepath: Path) -> bool:
    """Parse a .env file and populate os.environ without third-party libraries."""
    if not filepath.is_file():
        return False
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip outer quotes if present
                    if len(val) >= 2 and (
                        (val.startswith('"') and val.endswith('"')) or
                        (val.startswith("'") and val.endswith("'"))
                    ):
                        val = val[1:-1]
                    # Only set if key is not already defined in environment
                    if key and key not in os.environ:
                        os.environ[key] = val
        return True
    except Exception as exc:
        sys.stderr.write(f"[{SERVER_NAME}] Warning: Failed reading {filepath}: {exc}\n")
        return False


def _auto_discover_env() -> None:
    """Search and load .env from likely locations."""
    script_dir = Path(__file__).resolve().parent
    project_root = _find_project_root()
    candidates = [
        script_dir / ".env",
        project_root / ".env",
        Path.cwd() / ".env",
        Path.home() / ".config/jira/.env",
        Path.home() / ".jira.env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            _load_env_file(candidate)
            break


# Run auto-discovery on startup
_auto_discover_env()


def _get_config() -> Dict[str, str]:
    """Retrieve and validate Jira configuration from environment variables."""
    host = os.environ.get("JIRA_HOST", "").strip().rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()
    pat = os.environ.get("JIRA_PAT", "").strip()
    api_version = os.environ.get("JIRA_API_VERSION", "3").strip()

    if not host:
        raise ValueError(
            "JIRA_HOST environment variable is missing.\n"
            "Please set JIRA_HOST (e.g. 'https://your-domain.atlassian.net' or 'https://jira.yourcompany.com').\n"
            "Run 'python3 server.py --init-env' to generate a .env template."
        )

    if not pat and (not email or not api_token):
        raise ValueError(
            "Jira authentication credentials missing. Please configure either:\n"
            "  1. Jira Cloud: JIRA_EMAIL and JIRA_API_TOKEN (Generate at https://id.atlassian.com/manage-profile/security/api-tokens)\n"
            "  2. Jira Server/DC: JIRA_PAT (Personal Access Token)\n"
            "Run 'python3 server.py --init-env' to generate a .env template."
        )

    return {
        "host": host,
        "email": email,
        "api_token": api_token,
        "pat": pat,
        "api_version": api_version,
    }


def _resolve_download_dir(custom_path: Optional[str] = None) -> Path:
    """
    Resolve download directory safely relative to project root or configured JIRA_DOWNLOAD_DIR.
    Prevents AI agents from dumping downloads into ephemeral /tmp directories.
    """
    project_root = _find_project_root()
    env_dir = os.environ.get("JIRA_DOWNLOAD_DIR", "").strip() or ".scratchpads/downloads"

    base_dir = Path(env_dir).expanduser()
    if not base_dir.is_absolute():
        base_dir = (project_root / base_dir).resolve()
    else:
        base_dir = base_dir.resolve()

    if custom_path:
        p = Path(custom_path).expanduser()
        # If client passes a temporary sandbox path (e.g. /private/tmp/... or /tmp/...),
        # ignore the temp prefix and route to configured base_dir
        if str(p).startswith("/tmp") or str(p).startswith("/private/tmp"):
            return base_dir
        if p.is_absolute():
            return p.resolve()
        return (base_dir / p).resolve()

    return base_dir


def _format_size(size_bytes: int) -> str:
    """Format bytes into a human-readable size string."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# Jira HTTP API Client (Zero-Dependency urllib)
# ---------------------------------------------------------------------------

def _make_request(
    method: str,
    path_or_url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> Tuple[int, bytes, Dict[str, str]]:
    """Execute an authenticated HTTP request to Jira using standard library urllib."""
    config = _get_config()
    
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        full_url = path_or_url
    else:
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        full_url = f"{config['host']}{path}"

    if params:
        query_string = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if query_string:
            sep = "&" if "?" in full_url else "?"
            full_url = f"{full_url}{sep}{query_string}"

    req = urllib.request.Request(full_url, method=method.upper())
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", f"{SERVER_NAME}/{SERVER_VERSION}")

    if config["pat"]:
        req.add_header("Authorization", f"Bearer {config['pat']}")
    else:
        creds = f"{config['email']}:{config['api_token']}"
        encoded_creds = base64.b64encode(creds.encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {encoded_creds}")

    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    ssl_context = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            status_code = resp.status
            content = resp.read()
            resp_headers = dict(resp.headers.items())
            return status_code, content, resp_headers
    except urllib.error.HTTPError as err:
        error_body = ""
        try:
            error_body = err.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        if err.code == 401:
            raise PermissionError(
                "Jira Authentication failed (401). Please check JIRA_EMAIL and JIRA_API_TOKEN / JIRA_PAT."
            ) from err
        elif err.code == 403:
            raise PermissionError(
                f"Jira Access forbidden (403). You do not have permission for this resource.\nDetails: {error_body}"
            ) from err
        elif err.code == 404:
            raise FileNotFoundError(
                f"Jira resource not found (404) at {path_or_url}\nDetails: {error_body}"
            ) from err
        else:
            raise RuntimeError(
                f"Jira API HTTP Error {err.code}: {err.reason}\n{error_body}"
            ) from err
    except urllib.error.URLError as err:
        raise ConnectionError(
            f"Failed to connect to Jira host '{config['host']}': {err.reason}"
        ) from err


def _download_stream(url: str, target_file: Path, timeout: int = 120) -> int:
    """Download a file stream directly to local disk in chunks without high memory consumption."""
    config = _get_config()
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "*/*")
    req.add_header("User-Agent", f"{SERVER_NAME}/{SERVER_VERSION}")

    if config["pat"]:
        req.add_header("Authorization", f"Bearer {config['pat']}")
    else:
        creds = f"{config['email']}:{config['api_token']}"
        encoded_creds = base64.b64encode(creds.encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {encoded_creds}")

    ssl_context = ssl.create_default_context()
    total_bytes = 0

    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
        with open(target_file, "wb") as f:
            while True:
                chunk = resp.read(32768)
                if not chunk:
                    break
                f.write(chunk)
                total_bytes += len(chunk)

    return total_bytes


# ---------------------------------------------------------------------------
# ADF (Atlassian Document Format) Parser
# ---------------------------------------------------------------------------

def _extract_adf_text(node: Any, depth: int = 0) -> str:
    """
    Recursively converts Atlassian Document Format (ADF) JSON structure
    into clean, readable Markdown/plaintext.
    """
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(filter(None, (_extract_adf_text(item, depth) for item in node)))
    if not isinstance(node, dict):
        return str(node)

    node_type = node.get("type", "")
    content = node.get("content", [])
    text = node.get("text", "")

    # Formatting marks (strong, em, code, link)
    marks = node.get("marks", [])
    for mark in marks:
        m_type = mark.get("type", "")
        if m_type == "code":
            text = f"`{text}`"
        elif m_type == "strong":
            text = f"**{text}**"
        elif m_type == "em":
            text = f"*{text}*"
        elif m_type == "link":
            href = mark.get("attrs", {}).get("href", "")
            text = f"[{text}]({href})" if href else text

    if node_type == "text":
        return text

    if node_type == "paragraph":
        inner = "".join(_extract_adf_text(c, depth) for c in content)
        return f"{inner}\n"

    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 1)
        prefix = "#" * max(1, min(6, level))
        inner = "".join(_extract_adf_text(c, depth) for c in content)
        return f"{prefix} {inner}\n"

    if node_type == "bulletList":
        items = [_extract_adf_text(c, depth + 1) for c in content]
        return "\n".join(f"- {it.strip()}" for it in items if it.strip()) + "\n"

    if node_type == "orderedList":
        items = [_extract_adf_text(c, depth + 1) for c in content]
        return "\n".join(f"{idx+1}. {it.strip()}" for idx, it in enumerate(items) if it.strip()) + "\n"

    if node_type == "listItem":
        return "".join(_extract_adf_text(c, depth) for c in content).strip()

    if node_type == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
        code_text = "".join(_extract_adf_text(c, depth) for c in content)
        return f"\n```{lang}\n{code_text}\n```\n"

    if node_type == "blockquote":
        inner = "".join(_extract_adf_text(c, depth) for c in content)
        lines = [f"> {line}" for line in inner.splitlines()]
        return "\n".join(lines) + "\n"

    if node_type == "rule":
        return "\n---\n"

    if node_type in ("table", "tableRow", "tableHeader", "tableCell"):
        sub = " | ".join(filter(None, (_extract_adf_text(c, depth).strip() for c in content)))
        return f"| {sub} |" if node_type == "tableRow" else sub

    # Generic container fallback
    if content:
        return "".join(_extract_adf_text(c, depth) for c in content)

    return text


# ---------------------------------------------------------------------------
# Jira Tools Implementation
# ---------------------------------------------------------------------------

def jira_get_issue(issue_key: str) -> Dict[str, Any]:
    """
    Fetch details for a Jira issue by its key (e.g. 'PROJ-123'), including
    summary, description, status, assignee, reporter, and all attachment metadata.
    """
    config = _get_config()
    v = config["api_version"]
    key = str(issue_key).strip().upper()
    
    _, content, _ = _make_request("GET", f"/rest/api/{v}/issue/{urllib.parse.quote(key)}")
    data = json.loads(content.decode("utf-8"))
    fields = data.get("fields", {})

    raw_desc = fields.get("description")
    if isinstance(raw_desc, dict):
        description = _extract_adf_text(raw_desc).strip()
    elif isinstance(raw_desc, str):
        description = raw_desc.strip()
    else:
        description = ""

    attachments = []
    for att in fields.get("attachment", []):
        size_b = att.get("size", 0)
        attachments.append({
            "id": str(att.get("id")),
            "filename": att.get("filename"),
            "mimeType": att.get("mimeType"),
            "size_bytes": size_b,
            "size_human": _format_size(size_b),
            "created": att.get("created"),
            "author": att.get("author", {}).get("displayName"),
            "content_url": att.get("content"),
        })

    return {
        "key": data.get("key"),
        "summary": fields.get("summary"),
        "status": fields.get("status", {}).get("name"),
        "priority": fields.get("priority", {}).get("name") if fields.get("priority") else None,
        "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else "Unassigned",
        "reporter": fields.get("reporter", {}).get("displayName") if fields.get("reporter") else None,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "description": description,
        "attachment_count": len(attachments),
        "attachments": attachments,
    }


def jira_list_attachments(issue_key: str) -> List[Dict[str, Any]]:
    """
    List all attachments for a specific Jira issue (e.g. 'PROJ-123')
    with their ID, filename, size, and MIME type.
    """
    issue = jira_get_issue(issue_key)
    return issue.get("attachments", [])


def jira_download_attachment(
    attachment_id: str,
    filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download a single Jira attachment by its ID and save it to a local folder.
    """
    config = _get_config()
    v = config["api_version"]
    att_id = str(attachment_id).strip()

    if not filename:
        try:
            _, meta_bytes, _ = _make_request("GET", f"/rest/api/{v}/attachment/{att_id}")
            meta = json.loads(meta_bytes.decode("utf-8"))
            filename = meta.get("filename", f"attachment_{att_id}")
        except Exception:
            filename = f"attachment_{att_id}"

    dest_folder = _resolve_download_dir(output_dir)
    dest_folder.mkdir(parents=True, exist_ok=True)
    target_path = dest_folder / filename

    content_url = f"{config['host']}/rest/api/{v}/attachment/content/{att_id}"
    total_bytes = _download_stream(content_url, target_path)

    return {
        "status": "success",
        "attachment_id": att_id,
        "filename": filename,
        "saved_path": str(target_path),
        "size_bytes": total_bytes,
        "size_human": _format_size(total_bytes),
    }


def jira_download_all_attachments(
    issue_key: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download all attachments associated with a Jira issue into a local directory.
    """
    issue = jira_get_issue(issue_key)
    attachments = issue.get("attachments", [])

    if not attachments:
        return {
            "issue_key": issue_key,
            "message": "No attachments found for this issue.",
            "downloaded_files": [],
        }

    base_dir = _resolve_download_dir(output_dir)
    target_dir = base_dir / issue_key.strip().upper()
    target_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for att in attachments:
        att_id = att["id"]
        fname = att["filename"]
        res = jira_download_attachment(
            attachment_id=att_id,
            filename=fname,
            output_dir=str(target_dir),
        )
        results.append(res)

    return {
        "issue_key": issue_key,
        "total_downloaded": len(results),
        "target_directory": str(target_dir),
        "downloaded_files": results,
    }


def jira_read_text_attachment(
    attachment_id: str,
    max_chars: int = 50000,
) -> Dict[str, Any]:
    """
    Read the contents of a text-based attachment (logs, JSON, CSV, code, markdown, txt)
    directly into context without saving to disk.
    """
    config = _get_config()
    v = config["api_version"]
    att_id = str(attachment_id).strip()

    try:
        _, meta_bytes, _ = _make_request("GET", f"/rest/api/{v}/attachment/{att_id}")
        meta = json.loads(meta_bytes.decode("utf-8"))
        filename = meta.get("filename", f"attachment_{att_id}")
        mime_type = meta.get("mimeType", "text/plain")
    except Exception:
        filename = f"attachment_{att_id}"
        mime_type = "unknown"

    _, raw_content, _ = _make_request(
        "GET",
        f"/rest/api/{v}/attachment/content/{att_id}",
        headers={"Accept": "*/*"},
    )

    try:
        text_content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text_content = raw_content.decode("latin-1")
        except Exception as e:
            return {
                "error": f"Failed to decode attachment as text: {str(e)}",
                "filename": filename,
                "mime_type": mime_type,
            }

    truncated = False
    if len(text_content) > max_chars:
        text_content = text_content[:max_chars]
        truncated = True

    return {
        "attachment_id": att_id,
        "filename": filename,
        "mime_type": mime_type,
        "character_count": len(text_content),
        "is_truncated": truncated,
        "content": text_content,
    }


def jira_search_issues(jql: str, max_results: int = 10) -> Dict[str, Any]:
    """
    Search Jira issues using JQL (Jira Query Language).
    """
    config = _get_config()
    v = config["api_version"]
    params = {
        "jql": jql,
        "maxResults": max_results,
        "fields": "summary,status,assignee,attachment,created,updated",
    }

    # Jira Cloud API v3 uses /search/jql; v2 uses /search
    search_path = f"/rest/api/{v}/search/jql" if str(v) == "3" else f"/rest/api/{v}/search"

    try:
        _, content, _ = _make_request("GET", search_path, params=params)
    except Exception:
        # Fallback to /search if /search/jql is not supported
        _, content, _ = _make_request("GET", f"/rest/api/{v}/search", params=params)

    data = json.loads(content.decode("utf-8"))

    issues = []
    for item in data.get("issues", []):
        fields = item.get("fields", {})
        att_list = fields.get("attachment", [])
        issues.append({
            "key": item.get("key"),
            "summary": fields.get("summary"),
            "status": fields.get("status", {}).get("name"),
            "assignee": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else "Unassigned",
            "attachment_count": len(att_list),
            "attachments": [
                {
                    "id": str(a.get("id")),
                    "filename": a.get("filename"),
                    "size_human": _format_size(a.get("size", 0)),
                }
                for a in att_list
            ],
        })

    return {
        "total": data.get("total", 0),
        "returned": len(issues),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# MCP Tool Schemas & Tool Registry
# ---------------------------------------------------------------------------

TOOLS_SPEC = [
    {
        "name": "jira_get_issue",
        "description": "Fetch details for a Jira issue by its key (e.g. 'PROJ-123'), including summary, description (ADF parsed), status, assignee, reporter, and metadata of all attachments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key, e.g. 'PROJ-123'.",
                }
            },
            "required": ["issue_key"],
        },
        "handler": jira_get_issue,
    },
    {
        "name": "jira_list_attachments",
        "description": "List all attachments for a specific Jira issue with their ID, filename, size, and MIME type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key, e.g. 'PROJ-123'.",
                }
            },
            "required": ["issue_key"],
        },
        "handler": jira_list_attachments,
    },
    {
        "name": "jira_download_attachment",
        "description": "Download a single Jira attachment by its ID and save it to the project download directory (JIRA_DOWNLOAD_DIR).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The numerical ID of the attachment in Jira (e.g. '10045').",
                },
                "filename": {
                    "type": "string",
                    "description": "(Optional) Destination filename. If omitted, fetched automatically from Jira metadata.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "(Optional) Relative subdirectory to save the file. Omit this to use the project default JIRA_DOWNLOAD_DIR (.scratchpads/downloads). Do NOT use temporary /tmp directories.",
                },
            },
            "required": ["attachment_id"],
        },
        "handler": jira_download_attachment,
    },
    {
        "name": "jira_download_all_attachments",
        "description": "Download all attachments associated with a Jira issue into a folder under JIRA_DOWNLOAD_DIR (e.g. .scratchpads/downloads/<ISSUE_KEY>).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key (e.g. 'PROJ-123').",
                },
                "output_dir": {
                    "type": "string",
                    "description": "(Optional) Base directory. Omit this to use the project default JIRA_DOWNLOAD_DIR (.scratchpads/downloads). Do NOT use temporary /tmp directories.",
                },
            },
            "required": ["issue_key"],
        },
        "handler": jira_download_all_attachments,
    },
    {
        "name": "jira_read_text_attachment",
        "description": "Read the contents of a text-based attachment (logs, JSON, CSV, code, markdown, txt) directly into memory context without writing to disk.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "attachment_id": {
                    "type": "string",
                    "description": "The Jira attachment ID.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 50,000 to prevent context overflow).",
                    "default": 50000,
                },
            },
            "required": ["attachment_id"],
        },
        "handler": jira_read_text_attachment,
    },
    {
        "name": "jira_search_issues",
        "description": "Search Jira issues using JQL (Jira Query Language).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "jql": {
                    "type": "string",
                    "description": "The JQL query string (e.g. 'project = PROJ AND status = \"In Progress\"').",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of issues to return (default: 10).",
                    "default": 10,
                },
            },
            "required": ["jql"],
        },
        "handler": jira_search_issues,
    },
]

TOOL_HANDLERS = {tool["name"]: tool["handler"] for tool in TOOLS_SPEC}


# ---------------------------------------------------------------------------
# Universal Stdio JSON-RPC 2.0 MCP Protocol Server
# ---------------------------------------------------------------------------

def _send_json_rpc(response_dict: Dict[str, Any]) -> None:
    """Send a JSON-RPC response to stdout followed by newline and flush immediately."""
    payload = json.dumps(response_dict, ensure_ascii=False)
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def _handle_json_rpc_message(msg: Dict[str, Any]) -> None:
    """Handle a single MCP JSON-RPC 2.0 request or notification."""
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    # Notification (no id field)
    if msg_id is None:
        if method == "notifications/initialized":
            sys.stderr.write(f"[{SERVER_NAME}] Client initialized successfully.\n")
        return

    # Request handlers
    if method == "initialize":
        _send_json_rpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        })
        return

    if method == "ping":
        _send_json_rpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {},
        })
        return

    if method == "tools/list":
        tools_list = [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for t in TOOLS_SPEC
        ]
        _send_json_rpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": tools_list,
            },
        })
        return

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_HANDLERS:
            _send_json_rpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: Unknown tool '{tool_name}'",
                        }
                    ],
                    "isError": True,
                },
            })
            return

        handler = TOOL_HANDLERS[tool_name]
        try:
            result = handler(**tool_args)
            text_output = json.dumps(result, indent=2, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
            _send_json_rpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text_output,
                        }
                    ],
                    "isError": False,
                },
            })
        except Exception as exc:
            _send_json_rpc({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Tool execution failed: {type(exc).__name__}: {str(exc)}",
                        }
                    ],
                    "isError": True,
                },
            })
        return

    if method in ("resources/list", "prompts/list"):
        field_name = method.split("/")[0]
        _send_json_rpc({
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                field_name: [],
            },
        })
        return

    # Method not found
    _send_json_rpc({
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {
            "code": -32601,
            "message": f"Method '{method}' not found",
        },
    })


def run_stdio_server() -> None:
    """Main JSON-RPC stdio event loop."""
    sys.stderr.write(f"[{SERVER_NAME}] Starting stdio transport (MCP v{MCP_PROTOCOL_VERSION})...\n")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            # Handle possible Content-Length header prefix if sent by certain clients
            if line.startswith("Content-Length:"):
                length = int(line.split(":", 1)[1].strip())
                # Read empty line separating header from body
                sys.stdin.readline()
                body = sys.stdin.read(length)
                msg = json.loads(body)
            else:
                msg = json.loads(line)

            if isinstance(msg, dict):
                _handle_json_rpc_message(msg)
        except (KeyboardInterrupt, BrokenPipeError):
            break
        except json.JSONDecodeError as err:
            sys.stderr.write(f"[{SERVER_NAME}] JSON decode error: {err}\n")
        except Exception as exc:
            sys.stderr.write(f"[{SERVER_NAME}] Unexpected loop error: {exc}\n")


# ---------------------------------------------------------------------------
# CLI Diagnostics & Self-Test Mode
# ---------------------------------------------------------------------------

def run_test_mode() -> None:
    """Test Jira connectivity and print diagnostic status."""
    print(f"=== {SERVER_NAME} v{SERVER_VERSION} Diagnostics ===")
    try:
        cfg = _get_config()
        print(f"✔ Host: {cfg['host']}")
        if cfg['pat']:
            print("✔ Auth: Personal Access Token (PAT)")
        else:
            print(f"✔ Auth: Basic Auth ({cfg['email']} + API Token)")
        print(f"✔ API Version: {cfg['api_version']}")
        print(f"✔ Download Directory: {_resolve_download_dir()}")

        print("\nTesting connectivity to Jira API...")
        v = cfg["api_version"]
        status, content, _ = _make_request("GET", f"/rest/api/{v}/myself")
        if status == 200:
            user_data = json.loads(content.decode("utf-8"))
            display_name = user_data.get("displayName", "Unknown")
            email = user_data.get("emailAddress", "N/A")
            active = user_data.get("active", True)
            print(f"✔ Connection successful! Logged in as: {display_name} ({email}) [Active: {active}]")
        else:
            print(f"⚠ Unexpected response status: {status}")
    except Exception as exc:
        print(f"✖ Diagnostics failed: {type(exc).__name__}: {exc}")
        sys.exit(1)


def run_init_env() -> None:
    """Create a default .env file in the script directory if it doesn't already exist."""
    script_dir = Path(__file__).resolve().parent
    target = script_dir / ".env"
    if target.exists():
        print(f"ℹ .env file already exists at: {target}")
        return

    example_candidates = [
        script_dir / ".env.example",
        script_dir / ".env.sample",
    ]
    content = None
    for cand in example_candidates:
        if cand.is_file():
            content = cand.read_text(encoding="utf-8")
            break

    if not content:
        content = DEFAULT_ENV_TEMPLATE

    target.write_text(content, encoding="utf-8")
    print(f"✔ Created .env template at: {target}")
    print("Please edit the file and fill in your Jira credentials.")


def run_tools_list_cli() -> None:
    """Print registered tools in JSON format."""
    out = [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["inputSchema"],
        }
        for t in TOOLS_SPEC
    ]
    print(json.dumps(out, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{SERVER_NAME} - Universal Zero-Dependency Jira MCP Server"
    )
    parser.add_argument("--test", action="store_true", help="Test Jira connectivity and auth")
    parser.add_argument("--init-env", action="store_true", help="Create a .env file template")
    parser.add_argument("--tools", action="store_true", help="List registered MCP tools and schemas")
    parser.add_argument("--stdio", action="store_true", help="Run MCP server over stdio (default)")

    args = parser.parse_args()

    if args.test:
        run_test_mode()
    elif args.init_env:
        run_init_env()
    elif args.tools:
        run_tools_list_cli()
    else:
        run_stdio_server()


if __name__ == "__main__":
    main()
