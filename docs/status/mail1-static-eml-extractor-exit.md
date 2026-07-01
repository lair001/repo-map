# MAIL1 Static EML Extractor Exit

Status: complete.

Date: 2026-07-01

## Scope

MAIL1 implements ADR 0022's first local email extraction slice for single
`.eml` files. The implementation parses local bytes only, emits conservative
email raw observations, canonicalizes generic `email.*` graph facts, and loads
through the existing raw/canonical storage path.

MAIL1 does not implement MBOX parsing, provider APIs, mailbox mutation,
attachment content extraction, body text indexing, HTML rendering, JavaScript
execution, provider-specific namespaces, MCP tools, storage migrations, public
readback default changes, or Phase F migration behavior.

## Parser Strategy

MAIL1 uses Python stdlib `email` parsing through `BytesParser` with the default
email policy. The parser reads local bytes only and does not fetch, render, or
execute anything.

The extractor enforces bounded parsing limits for:

- maximum EML file bytes;
- maximum total header bytes;
- maximum MIME part count.

Malformed messages, parser defects, oversized files, oversized header blocks,
and MIME part limit failures emit `email.parse_error` observations. A malformed
message can still produce safe file/message diagnostics, but MAIL1 does not
fabricate precise body, attachment, or thread facts from unsafe input.

## Discovery

Discovery routes `.eml` files to the MAIL1 extractor with language `eml`.

MAIL1 does not add `.mbox`, `.mailbox`, extensionless mailbox, Gmail, IMAP,
SMTP, Microsoft Graph, OAuth, or provider discovery routes. Existing Python,
Nix, shell, Ruby, JavaScript, Markdown, JSON/TOML/YAML config, XML/plist,
DOCS, HTML/CSS, ARCHIVE/WARC, and feed routing remains unchanged.

## Raw Observations

MAIL1 emits these raw observation kinds:

- `email.message`
- `email.header`
- `email.address`
- `email.part`
- `email.attachment_stub`
- `email.thread_hint`
- `email.reference`
- `email.parse_error`

`email.mailbox` remains deferred to MAIL2. Body-content observations,
attachment-content observations, provider observations, and list-header
canonical nodes are not implemented in MAIL1.

## Canonical Graph

MAIL1 implements generic email namespaces only:

- `email.message:<encoded-message-identity>`
- `email.address:<encoded-address-hash-or-domain-scoped-key>`
- `email.part:<encoded-message-key>:<encoded-part-path>`
- `email.attachment_stub:<encoded-message-key>:<encoded-attachment-pointer>`
- `email.thread_hint:<encoded-message-key>:<encoded-thread-pointer>`

Edges use existing vocabulary only:

- `file:* --defines--> email.message:*`
- `email.message:* --defines--> email.part:*`
- `email.message:* --defines--> email.attachment_stub:*`
- `email.message:* --defines--> email.thread_hint:*`
- `email.message:* --references--> email.address:*`
- `email.message:* --references--> email.message:* | unknown:*` for
  header thread references
- `email.message:* --references--> external.url:*` for safe not-fetched header
  URL references

No `gmail.*`, `imap.*`, `smtp.*`, `outlook.*`, `microsoft.*`, `exchange.*`,
body-content, attachment-content, or provider-specific namespaces were added.
No new edge kinds were added.

## Message Identity

Message identity prefers a valid normalized `Message-ID` hashed into a safe
canonical key, scoped by source file context. If `Message-ID` is missing or
invalid, MAIL1 falls back to a deterministic structural identity derived from
safe file/header facts and emits a parse diagnostic.

Message identity never uses raw subject text, line numbers alone, import time,
parser object IDs, mutable provider IDs, or generated summaries. Body hashes
may be used only as non-serialized structural input; body values are not stored.

## Address Handling

MAIL1 emits canonical `email.address:*` nodes using hashed address identity.
Safe address metadata includes role, domain, hash, count fields, and redaction
status. Raw full email addresses and display names are omitted from canonical
keys, raw metadata, canonical metadata, edge metadata, readback, and explain
output.

Address observations are evidence for message participation only. MAIL1 does
not do contact enrichment, address book lookup, sender verification, or provider
identity reconciliation.

## Subject Behavior

MAIL1 records subject presence and `subject_hash`. When a preview is present,
it is a bounded redacted placeholder rather than raw subject text.

Raw unredacted subjects are not stored in canonical keys, raw metadata,
canonical node metadata, edge metadata, fixtures, readback, or explain output.

## MIME And Body Parts

MAIL1 records MIME structure and body-part metadata only:

- MIME/content type;
- charset;
- transfer encoding;
- content disposition;
- part path, index, and depth;
- part byte count;
- text/plain and text/html part counts;
- `has_text_plain` and `has_text_html` flags.

MAIL1 does not store body text, raw HTML, rendered HTML, DOM facts, body URL
facts, body snippets, LLM summaries, or body-derived canonical nodes. `text/html`
parts are treated as sensitive MIME parts only and are not routed to the HTML
extractor in MAIL1.

## Attachment Stubs

MAIL1 implements attachment stubs only. Safe stub metadata includes:

- redacted/sanitized filename placeholder;
- filename hash;
- attachment MIME type;
- byte count;
- content disposition;
- part path;
- inline flag;
- content-id presence.

MAIL1 does not extract attachment text, store attachment bodies, parse PDFs,
DOCX, XLSX, archives, images, or nested formats, OCR images, render images,
decode macros, or execute attachments.

## Thread And References

MAIL1 supports header-first thread hints:

- `In-Reply-To`
- each `References` message-id token

Thread hints are evidence, not authoritative provider threads. MAIL1 does not
infer conversations from quoted body text, normalized subject fallback,
provider thread IDs, ML clustering, or LLM summaries.

`Message-ID`, `In-Reply-To`, and `References` values are normalized and hashed
or summarized before graphing. References to messages outside the imported set
use deterministic `unknown:email-message:*` placeholders.

MAIL1 also records safe, redacted `List-Unsubscribe` header URL or mailto
references as `external.url:*` with `not_fetched=true`. Header URLs have
credentials and tracking/secret-prone query values stripped or redacted.

MAIL1 does not extract body URLs in this phase.

## Malformed EML Behavior

Malformed or incomplete EML input emits `email.parse_error` diagnostics for
parser defects, missing/invalid message identity, file-size limits, header-size
limits, and MIME part limits. Diagnostics are raw/evidence-only and do not add
provider semantics or fabricated precise facts.

## Redaction

MAIL1 reuses ADR 0010/YAML/Ruby/JS secret markers and adds the MAIL0
email/person markers, including one-time codes, verification/reset links,
unsubscribe tokens, tracking pixels, auth links, invoice/account/tax/medical
markers, routing and credit-card markers, and related sensitive terms.

Redaction rules ensure that:

- raw full email addresses do not appear in canonical keys, metadata, readback,
  or explain;
- display names do not appear in canonical keys, metadata, readback, or explain;
- raw subjects do not appear in canonical keys, metadata, readback, or explain;
- body text and raw HTML do not appear in graph metadata, readback, or explain;
- attachment content does not appear in graph metadata, readback, or explain;
- secret values do not appear in raw observation metadata, canonical node
  metadata, edge metadata, fixtures, readback, or explain;
- URL credentials and secret-prone query parameters are stripped or redacted.

Headers and bodies are treated as sensitive by default. Header observations
record only safe presence/count/name metadata unless a specific redacted summary
is explicitly safe.

## Fixture Coverage

MAIL1 adds discovery fixtures under:

```text
src/test/fixtures/discovery/mail_basic/
```

Fixtures include:

- `single-message.eml`
- `thread-reply.eml`
- `multipart-alternative.eml`
- `attachment-stub.eml`
- `inline-cid.eml`
- `malformed.eml`
- `redaction.eml`
- `large-body.eml`

MAIL1 also adds canonicalization fixtures under:

```text
src/test/fixtures/canonicalization/mail_basic/
```

The fixture corpus covers simple EML parsing, missing/invalid Message-ID
fallback identity, date metadata, address role counts and hashes, subject
hash/redaction, MIME part metadata, text/plain and text/html part counts,
attachment stubs, inline CID metadata, thread hints, safe `List-Unsubscribe`
metadata, malformed input diagnostics, and redaction.

Fixtures use fake values and reserved example domains only. They do not include
real email addresses, real personal names, private domains, private endpoints,
real tokens, real message bodies, or private correspondence.

## Storage And Readback

MAIL1 uses the existing storage path:

- raw observations are retained in `raw_observations`;
- generic `email.*` canonical nodes are stored in canonical graph tables;
- existing `defines` and `references` edges are used;
- legacy public readback defaults are unchanged.

Useful readback examples:

```bash
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.message --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.part --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.attachment_stub --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.thread_hint --json
repomap-kg storage edges --root-path src/test/fixtures/discovery/mail_basic --kind references --json
repomap-kg storage explain-canonical-edge --root-path src/test/fixtures/discovery/mail_basic --source-key '<email-message-key>' --kind references --target-key '<unknown-email-message-target>' --json
```

Storage tests verify that readback and explain output omit raw full email
addresses, raw display names, raw subjects, body text, attachment content,
tracking values, and fake secret marker values.

## Known Gaps

- MBOX parsing is deferred to MAIL2.
- Email readback polish and summary commands are deferred to MAIL3.
- Body URL extraction is deferred.
- Body text snippets and body-content nodes are deferred.
- Attachment content extraction, attachment parsing, OCR, archive opening, and
  macro decoding remain out of scope.
- Exact provider thread reconstruction is not attempted.
- Gmail, IMAP, SMTP, Microsoft Graph, OAuth, provider login, provider sync, and
  provider mutation are out of scope.

## Guardrail Confirmation

MAIL1 does not parse MBOX, connect to Gmail, IMAP, SMTP, Microsoft Graph, or
any provider, prompt for credentials, use OAuth, mutate mailboxes, send,
forward, delete, archive, label, or mark mail read/unread, fetch remote images,
fetch tracking pixels, crawl links, fetch `Content-Location`, fetch or resolve
`cid:` references externally, execute HTML, render HTML, execute JavaScript,
execute attachments, parse attachment contents, OCR images, parse PDFs, DOCX,
XLSX, or archives, decode macros, store raw body text in canonical metadata,
store attachment bodies, expose raw full email addresses, display names, or raw
subjects in readback/explain, add provider namespaces, add MCP tools, add
storage migrations, change public readback defaults, or resume Phase F.
