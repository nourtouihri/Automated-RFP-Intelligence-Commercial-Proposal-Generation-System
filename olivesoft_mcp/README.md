# olivesoft_mcp

A **read-only** MCP server over the OliveSoft RFP services. It lets Claude (Desktop, Code or any MCP
client) browse detected tenders, read stored prospect research, search the CV/project/tool index and
inspect generated proposals, using the same services and token as the n8n workflow and the UI.

It never starts research, builds a deck, ingests a tender or writes a file. Those stay in the UI and
n8n, where a person confirms them.

> The folder is `olivesoft_mcp/`, not `mcp/`: a top-level `mcp/` package would shadow the MCP SDK's own
> `mcp` import.

## Tools

| Tool | Reads | Use it for |
| --- | --- | --- |
| `olivesoft_check_services` | every `/health` (no token) | "is the stack up?" |
| `olivesoft_list_tenders` | detection `GET /tenders` | find an id; filter by status or text; paginated |
| `olivesoft_get_tender` | detection `GET /tenders/{id}` | requirements, deadline, raw-text excerpt |
| `olivesoft_get_research` | research `GET /research/{id}` | sector, revenue, past projects, partners, sources |
| `olivesoft_search_knowledge_base` | RAG `POST /query` | free-text questions over CVs, projects, tools |
| `olivesoft_match_team_for_tender` | detection + RAG `POST /query` x2 | best CVs and projects for a tender, as n8n computes them |
| `olivesoft_get_proposal` | proposal `GET /proposal/{id}` | bid/no-bid, Strong/Partial/Gap matrix, team, warnings, file names |

All seven carry `readOnlyHint: true`. Every tool takes `response_format` (`markdown` default, or `json`).

`olivesoft_match_team_for_tender` builds its query the way n8n's "Prepare RAG Context" does today (title,
issuer, then each requirement) and runs one `cv` and one `project` search with `top_k` 5 and
`similarity_threshold` 0.20. Similarity labels follow the proposal service's cut-offs: 0.55+ Strong,
0.40 to 0.55 Partial (needs a human check), below 0.40 Gap.

Search hits show the metadata keys the RAG index actually stores (`record_id`, `person`, `name`, `role`,
`skills`, `tech_stack`, `client`, `client_sector`, `category`, `domains`, `evidence_status` — see
`rag/structured_chunking.py`'s `record_meta`).

## Run it

```bash
pip install "mcp>=1.2,<2" httpx pydantic     # already in the root requirements.txt
export INTERNAL_SERVICE_TOKEN=...            # same value the stack runs with
python -m olivesoft_mcp                      # stdio
```

Service addresses default to `localhost:8000` (detection), `8001` (RAG), `8002` (research), `8003`
(proposal), `8004` (ingestion), `5678` (n8n). Override with `UIP_DETECTION_URL`, `UIP_RAG_URL`,
`UIP_RESEARCH_URL`, `UIP_PROPOSAL_URL`, `UIP_INGESTION_URL`, `UIP_N8N_URL` (the same names the UI proxy uses).

**Claude Code**

```bash
claude mcp add olivesoft --env INTERNAL_SERVICE_TOKEN=... -- python -m olivesoft_mcp
```

(run it from the repo root so `olivesoft_mcp` is importable, or add `--scope user` and use an absolute `cwd` in the config below)

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "olivesoft": {
      "command": "python",
      "args": ["-m", "olivesoft_mcp"],
      "cwd": "/path/to/Submission-2-main",
      "env": { "INTERNAL_SERVICE_TOKEN": "..." }
    }
  }
}
```

Inspect it with `npx @modelcontextprotocol/inspector python -m olivesoft_mcp`.

HTTP is available with `OLIVESOFT_MCP_TRANSPORT=streamable-http` (`OLIVESOFT_MCP_HOST`, default
`127.0.0.1`; `OLIVESOFT_MCP_PORT`, default `8010`). **It has no authentication.** Keep it on loopback;
do not tunnel it.

## Security notes

- The token is read from the server's environment only. It is sent as `X-Internal-Token`, scrubbed from
  any service message, and never returned in tool output.
- Errors name the service and the next step. They never contain a URL, the token or a stack trace.
- Tender text, research notes and document excerpts are untrusted. They are stripped of control and
  bidi characters, truncated, and returned in a labelled `~~~external-data` block (markdown) or under a
  `data_notice` (json). The server instructions tell the model not to follow instructions found there.
- Inputs use `extra="forbid"`. Tender IDs are URL-encoded; proposal IDs must match the proposal
  service's own `^[A-Za-z0-9._-]{1,64}$` rule before any request is made.
- Every response is capped at 25,000 characters; lists are paginated.

## Tests

```bash
python -m pytest olivesoft_mcp -q      # 23 tests, httpx.MockTransport, no services needed
```

If CI installs only the root `requirements.txt`, add `mcp>=1.2,<2` there first, or collecting these
tests fails on import.

## Pitch demo

1. "Which tenders mention payroll, and which is closest to its deadline?" (`list_tenders`)
2. "Which CVs and past projects best fit tender-012, and how strong are they?" (`match_team_for_tender`)
3. "What do we know about its issuer?" (`get_research`)
4. "Did we generate a proposal? Is it a bid, and where are the Gaps?" (`get_proposal`)

## Not included, on purpose

`run_research` and `generate_deck` spend LLM and search budget. If you add them, gate them behind an
environment flag, require an explicit confirmation argument, cap calls per session, and use
`POST /research/{id}` and `POST /proposal/{id}` with the timeouts from the wiring plan (150 s and 180 s).

## MCP SDK 2.x

`mcp` 2.x renamed `FastMCP` to `MCPServer` (`mcp.server.mcpserver`), moved every
`mcp.server.fastmcp.*` module there (`ToolError` is now at `mcp.server.mcpserver.exceptions`),
and moved transport settings off the constructor (`host=`/`port=` are no longer accepted).
This server is written for 1.x and pinned below 2; migrating means renaming the imports
*and* moving `host`/`port` into the `mcp.run(...)` call.
