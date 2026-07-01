# MAIL3 Email Readback Polish Exit

Status: complete.

Date: 2026-07-01

## Scope

MAIL3 makes MAIL1 and MAIL2 local email graph facts easier to inspect without
adding new email extraction semantics. It adds a read-only storage summary for
generic `email.*` facts and extends storage/readback coverage for:

- `.eml` messages;
- `.mbox` mailbox containers and contained messages;
- hashed address facts;
- MIME/body-part metadata;
- attachment stubs;
- thread hints and message references;
- safe not-fetched header references;
- parse-error and limit diagnostics.

MAIL3 does not add provider-specific namespaces, edge kinds, storage migrations,
MCP tools, BULK/API behavior, public readback default changes, or Phase F
migration behavior.

## Readback Surface

MAIL3 adds one read-only CLI command:

```sh
repomap-kg storage email-summary --root-path <repo> --json
```

The command queries existing `canonical_nodes`, `canonical_edges`, and
`raw_observations` rows. It does not load files, parse email again, mutate
storage, read attachment bodies, render HTML, fetch network resources, crawl
links, or call mail providers.

The JSON output includes:

- EML message counts;
- MBOX mailbox and contained-message counts;
- total message counts;
- canonical address counts and raw address observation counts;
- distinct safe address-domain counts;
- MIME part, text/plain part, and text/html part counts;
- attachment-stub, inline attachment, and content-id counts;
- thread-hint counts;
- message-reference counts;
- safe external URL and `List-Unsubscribe` reference counts;
- parse-error and malformed/oversized diagnostic counts;
- Message-ID present and missing/invalid counts;
- messages-with-attachments, messages-with-HTML, and messages-with-plain-text
  counts;
- mailbox limit counts;
- `no_provider_api=true`, `no_mutation=true`, `no_body_text=true`, and
  `no_attachment_content=true` as explicit readback contract markers.

The table output presents the same fields for terminal use.

## Summary Behavior

MAIL3 summarizes existing MAIL1/MAIL2 facts only. It does not create new graph
keys, infer provider state, reconstruct conversations, search bodies, summarize
messages, parse attachments, or reinterpret raw MIME evidence.

The summary command is safe for empty repositories. When no local email facts
exist, it returns zero counts with the same explicit safety markers.

## EML Readback

EML readback remains anchored on the MAIL1 graph path:

- `file:* --defines--> email.message:*`;
- `email.message:* --defines--> email.part:*`;
- `email.message:* --defines--> email.attachment_stub:*`;
- `email.message:* --defines--> email.thread_hint:*`;
- `email.message:* --references--> email.address:*`;
- `email.message:* --references--> email.message:* | unknown:*` for
  header thread references;
- `email.message:* --references--> external.url:*` for safe not-fetched header
  URL references when present.

`storage explain-canonical-edge` links these edges back to the raw email
observation evidence that produced them.

## MBOX Readback

MBOX readback remains anchored on the MAIL2 mailbox container path:

- `file:* --defines--> email.mailbox:*`;
- `email.mailbox:* --defines--> email.message:*`;
- contained messages reuse the same MAIL1 message, MIME, attachment-stub,
  address, thread, and reference behavior.

MAIL3 does not implement extensionless mailbox discovery, provider export
semantics, Gmail Takeout behavior, mailbox mutation, or BULK corpus import.

## Address Readback

Address readback is privacy-first. The summary reports aggregate address counts,
raw address observation counts, and distinct safe domain counts. Canonical
`email.address:*` nodes remain hashed, and safe metadata may include address
role, domain, hash, and redaction status.

Raw full email addresses and display names are not included in canonical keys,
canonical metadata, edge metadata, summary output, readback output, or explain
output.

## Subject Privacy

MAIL3 does not expose raw subjects. Existing MAIL1/MAIL2 subject behavior
remains in force:

- subject presence is safe metadata;
- `subject_hash` is safe metadata;
- bounded subject previews, where present, are redacted placeholders;
- raw unredacted subject text is not emitted by summary, readback, or explain.

## MIME And Body-Part Readback

MAIL3 reports MIME structure counts only:

- total `email.part` nodes;
- text/plain part counts;
- text/html part counts;
- messages with plain text;
- messages with HTML;
- content-id part counts.

It does not expose body text, body snippets, raw HTML, rendered HTML, DOM facts,
body URLs, LLM summaries, or body-derived canonical nodes. HTML parts remain
MIME metadata only and are not routed to the HTML extractor.

## Attachment-Stub Readback

MAIL3 reports attachment stubs only:

- total `email.attachment_stub` nodes;
- inline attachment counts;
- content-id counts;
- messages with attachments.

Attachment bodies, raw attachment filenames, attachment text, nested archives,
PDF/DOCX/XLSX contents, image OCR, rendered images, macros, and executable
attachment behavior remain out of scope. Existing sanitized/redacted filename
metadata and filename hashes remain the only attachment filename readback
surface.

## Thread And Reference Readback

MAIL3 summarizes header-first thread and reference facts:

- `email.thread_hint` counts;
- message reference counts for `In-Reply-To` and `References`;
- `unknown:email-message:*` placeholders for messages outside the loaded graph;
- safe not-fetched external URL references from headers when already emitted;
- `List-Unsubscribe` reference counts when present.

Thread hints remain evidence, not authoritative provider threads. MAIL3 does
not infer conversations from body quotes, subjects, provider thread IDs,
identity enrichment, ML clustering, or LLM summaries.

## Parse Errors And Limits

MAIL3 reports existing `email.parse_error` observations and malformed or
oversized diagnostic counts. MBOX mailbox limit metadata is summarized through
the `mailbox_limits` count.

The summary command does not retry parsing, reopen mailbox files, or inspect
bodies to derive additional diagnostics.

## Redaction

MAIL3 exposes aggregate counts and safe contract flags only. It does not expose:

- raw full email addresses;
- display names;
- raw subjects;
- body text;
- raw HTML;
- attachment content;
- raw attachment filenames;
- tracking values;
- cookie/auth values;
- fake secret marker values.

The storage/readback test asserts those values are absent from canonical node
readback, edge readback, explain output, JSON summary output, and table summary
output.

## Fixtures

MAIL3 uses the existing MAIL1/MAIL2 fixtures:

- `src/test/fixtures/discovery/mail_basic/`
- `src/test/fixtures/canonicalization/mail_basic/`

Those fixtures cover:

- single-message EML;
- EML without a valid Message-ID fallback path;
- malformed EML;
- multipart alternative EML with text/plain and text/html parts;
- attachment stubs;
- inline content-id metadata;
- safe redacted `List-Unsubscribe`;
- redaction cases with fake values only;
- MBOX with multiple messages;
- MBOX thread references;
- malformed MBOX diagnostics;
- message-count limit behavior through test-controlled limits.

No real email addresses, real names, private correspondence, real tokens,
private endpoints, or non-reserved real domains were added.

## Readback Examples

Example JSON shape:

```json
{
  "address_domains": 1,
  "addresses": 6,
  "attachment_stubs": 3,
  "eml_messages": 8,
  "mailboxes": 1,
  "mbox_messages": 2,
  "messages": 10,
  "mime_parts": 22,
  "no_attachment_content": true,
  "no_body_text": true,
  "no_mutation": true,
  "no_provider_api": true,
  "parse_errors": 2,
  "thread_hints": 5
}
```

Exact counts depend on the loaded repository or fixture, but the fields are
stable.

Explainability examples covered by tests include:

- an EML file defining an `email.message:*` node;
- an MBOX mailbox defining contained `email.message:*` nodes;
- a message referencing a hashed `email.address:*` node;
- a message referencing an `unknown:email-message:*` thread target;
- a message referencing a safe not-fetched `external.url:*` header target.

## Known Gaps

- MAIL3 adds only `email-summary`; finer commands such as
  `email-threads`, `email-attachments`, or `email-addresses` remain deferred.
- The summary is count-oriented. Detailed inspection still uses existing
  canonical node, canonical edge, and explain commands.
- Body text search, body snippets, attachment extraction, HTML rendering,
  provider threading, sender verification, contact enrichment, spam/phishing
  classification, and LLM summarization remain out of scope.
- MAIL3 does not implement BULK local corpus ingestion or API acquisition.

## Out Of Scope Confirmation

MAIL3 does not use Gmail APIs, IMAP, SMTP, Microsoft Graph, provider login,
OAuth, mailbox mutation, sending, forwarding, deleting, archiving, labeling,
read-state mutation, remote image loading, tracking pixel fetching, link
crawling, external asset retrieval, attachment execution, macro execution,
HTML execution, JavaScript execution, OCR, attachment-content parsing, HTML
rendering, raw address/subject/body/attachment exposure, provider namespaces,
MCP tools, migrations, public readback default changes, BULK behavior, API
behavior, or Phase F migration work.

## Verification

The MAIL3 slice was verified with:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

Results:

- unit: 599 tests passed; aggregate line coverage 85.2%;
- int: 152 tests passed; aggregate line coverage 85.1%;
- all: 751 tests passed; aggregate line coverage 85.2%;
- compileall: passed;
- `git diff --check`: passed;
- `git diff --cached --check`: passed.
