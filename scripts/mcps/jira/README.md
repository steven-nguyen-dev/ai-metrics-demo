# Jira MCP Server

Zero-dependency MCP server for Jira (Python 3 standard library only).

---

## Setup Credentials

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Open `.env` and fill in your Jira credentials (host, email, API token).

3. Verify connection:
```bash
python3 server.py --test
```

---

## Available Tools

| Tool | Description |
| :--- | :--- |
| `jira_get_issue` | Issue details, status, assignee, description, attachment metadata |
| `jira_search_issues` | JQL search (`jql`, `max_results`) |
| `jira_list_attachments` | List attachments for an issue |
| `jira_read_text_attachment` | Stream log/CSV/JSON text attachment directly into context |
| `jira_download_attachment` | Download single attachment (`attachment_id`, `output_dir`) |
| `jira_download_all_attachments` | Batch download all attachments (`issue_key`, `output_dir`) |
