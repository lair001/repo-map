# MAIL2 Static MBOX Extractor Exit

Status: complete.

Date: 2026-07-01

## Scope

MAIL2 implements ADR 0022's second local email extraction slice for `.mbox`
mailbox archive files. The implementation parses local bytes only, emits a
mailbox container observation, reuses MAIL1 per-message EML/MIME extraction
behavior for contained messages, canonicalizes generic `email.*` graph facts,
and loads through the existing raw/canonical storage path.

MAIL2 does not implement provider APIs, provider login, mailbox mutation, bulk
corpus orchestration, attachment content extraction, body text indexing, HTML
rendering, JavaScript execution, provider-specific namespaces, MCP tools,
storage migrations, public readback default changes, or Phase F migration
behavior.

## Parser Strategy

MAIL2 uses a small bounded local MBOX splitter rather than `mailbox.mbox`.
This keeps parsing read-only, avoids mailbox lock or mutation behavior, and
allows deterministic diagnostics for malformed input and limit failures.
Contained messages are parsed with the same Python stdlib `email` parser used
by MAIL1.

The extractor enforces bounded parsing limits for:

- maximum MBOX file bytes;
- maximum message count per MBOX;
- maximum per-message bytes;
- maximum total header bytes per message;
- maximum MIME part count per message.

Malformed archives, missing `From ` separators, oversized files, message-count
limits, per-message byte limits, header-size limits, MIME part limits, and
message parser defects emit `email.parse_error` observations. MAIL2 does not
fabricate precise message facts from malformed mailbox entries.

## Discovery

Discovery routes `.mbox` files to the MAIL2 extractor with language `mbox`.

MAIL2 does not add `.mailbox`, extensionless mailbox, Gmail Takeout, provider
API, or BULK recursive corpus discovery. Existing EML, Python, Nix, shell,
Ruby, JavaScript, Markdown, JSON/TOML/YAML config, XML/plist, DOCS, HTML/CSS,
ARCHIVE/WARC, and feed routing remains unchanged.

## Raw Observations

MAIL2 adds `email.mailbox` and reuses MAIL1 message observations:

- `email.mailbox`
- `email.message`
- `email.header`
- `email.address`
- `email.part`
- `email.attachment_stub`
- `email.thread_hint`
- `email.reference`
- `email.parse_error`

MAIL2 does not implement body-content observations, attachment-content
observations, provider observations, Gmail label observations, or provider
folder observations.

## Canonical Graph

MAIL2 implements the generic mailbox namespace:

- `email.mailbox:<encoded-file-key>`

It reuses MAIL1 namespaces for contained messages:

- `email.message:<encoded-message-identity>`
- `email.address:<encoded-address-hash-or-domain-scoped-key>`
- `email.part:<encoded-message-key>:<encoded-part-path>`
- `email.attachment_stub:<encoded-message-key>:<encoded-attachment-pointer>`
- `email.thread_hint:<encoded-message-key>:<encoded-thread-pointer>`

Edges use existing vocabulary only:

- `file:* --defines--> email.mailbox:*`
- `email.mailbox:* --defines--> email.message:*`
- `email.message:* --defines--> email.part:*`
- `email.message:* --defines--> email.attachment_stub:*`
- `email.message:* --defines--> email.thread_hint:*`
- `email.message:* --references--> email.address:*`
- `email.message:* --references--> email.message:* | unknown:*` for
  header thread references
- `email.message:* --references--> external.url:*` for safe not-fetched header
  URL references supported by MAIL1

No new edge kinds were added. No `gmail.*`, `imap.*`, `smtp.*`, `outlook.*`,
`microsoft.*`, `exchange.*`, body-content, attachment-content, or
provider-specific namespaces were added.

## Mailbox Identity

Mailbox identity is:

```text
email.mailbox:<encoded-file-key>
```

The mailbox key is derived from the repository-relative file key. It does not
use absolute machine paths, import timestamps, provider account names, mailbox
display labels, or mutable provider IDs.

Mailbox metadata is bounded and safe:

- `format: mbox`;
- file key;
- mailbox byte count;
- mailbox message count;
- message-count limit flag;
- parse status;
- limit reason;
- digest summary;
- identity strength.

## Per-Message Identity

Contained message identity reuses MAIL1 behavior and adds MBOX context.

Preferred identity is a valid normalized `Message-ID`, hashed into a safe
canonical key and scoped by mailbox file context. If `Message-ID` is missing or
invalid, MAIL2 falls back to a deterministic structural identity derived from
the mailbox file key, MBOX ordinal, safe header facts, and optional
non-serialized structural body hash input.

Per-message metadata includes `format: mbox`, `mailbox_file_key`,
`mbox_message_ordinal`, and `mbox_message_identity`.

Message identity never uses raw subject text, line numbers alone, import time,
parser object IDs, mutable provider IDs, generated summaries, or raw body
values.

## Reuse Of MAIL1 Behavior

MAIL2 reuses MAIL1 behavior for each contained message:

- hashed address identity only;
- no raw full address or display-name leakage;
- subject hash and redacted placeholder behavior;
- body metadata only;
- HTML body parts as MIME metadata only;
- attachment stubs only;
- header-first thread hints;
- safe not-fetched `List-Unsubscribe` references when present;
- no body URL extraction;
- no provider thread reconstruction.

## Address Handling

MAIL2 keeps MAIL1 address redaction and hashing. Canonical `email.address:*`
keys use hashed address identity. Safe metadata may include role, domain, hash,
count fields, and redaction status.

Raw full email addresses and display names are omitted from canonical keys, raw
metadata, canonical metadata, edge metadata, readback, and explain output.

## Subject Behavior

MAIL2 records subject presence and `subject_hash` for contained messages. A
preview, when present, is bounded and redacted rather than raw subject text.

Raw unredacted subjects are not stored in canonical keys, raw metadata,
canonical node metadata, edge metadata, fixtures, readback, or explain output.

## MIME And Body Parts

MAIL2 records MAIL1 MIME/body-part metadata only:

- MIME/content type;
- charset;
- transfer encoding;
- content disposition;
- part path, index, and depth;
- part byte count;
- text/plain and text/html part counts;
- `has_text_plain` and `has_text_html` flags.

MAIL2 does not store body text, raw HTML, rendered HTML, DOM facts, body URL
facts, body snippets, LLM summaries, or body-derived canonical nodes. `text/html`
parts are not routed to the HTML extractor.

## Attachment Stubs

MAIL2 implements MAIL1 attachment stubs for contained messages only. Safe stub
metadata includes:

- redacted/sanitized filename placeholder;
- filename hash;
- attachment MIME type;
- byte count;
- content disposition;
- part path;
- inline flag;
- content-id presence.

MAIL2 does not extract attachment text, store attachment bodies, parse PDFs,
DOCX, XLSX, archives, images, or nested formats, OCR images, render images,
decode macros, or execute attachments.

## Thread And References

MAIL2 supports header-first thread hints for contained messages:

- `In-Reply-To`;
- each `References` message-id token.

Thread hints remain evidence, not authoritative provider threads. MAIL2 does
not infer conversations from quoted body text, normalized subject fallback,
provider thread IDs, ML clustering, or LLM summaries.

References to messages outside the imported set use deterministic
`unknown:email-message:*` placeholders. Safe `List-Unsubscribe` URL or mailto
references are `external.url:*` with `not_fetched=true` and redaction, matching
MAIL1 behavior. MAIL2 does not extract body URLs.

## Malformed And Oversized MBOX Behavior

MAIL2 emits raw/evidence-only parse diagnostics for:

- missing MBOX `From ` separator;
- MBOX file-size limits;
- mailbox message-count limits;
- per-message byte limits;
- per-message header-size limits;
- per-message MIME part limits;
- stdlib email parser defects.

Large mailbox limit behavior is deterministic: the mailbox observation records
that the count was limited and `email.parse_error` records the limit reason.
Messages beyond the configured count limit are not parsed.

## Redaction

MAIL2 reuses MAIL1 redaction exactly. Redaction rules ensure that:

- raw full email addresses do not appear in canonical keys, metadata, readback,
  or explain;
- display names do not appear in canonical keys, metadata, readback, or explain;
- raw subjects do not appear in canonical keys, metadata, readback, or explain;
- body text and raw HTML do not appear in graph metadata, readback, or explain;
- attachment content does not appear in graph metadata, readback, or explain;
- secret values do not appear in raw observation metadata, canonical node
  metadata, edge metadata, fixtures, readback, or explain;
- URL credentials and secret-prone query parameters are stripped or redacted.

Headers and bodies are treated as sensitive by default.

## Fixture Coverage

MAIL2 extends discovery fixtures under:

```text
src/test/fixtures/discovery/mail_basic/
```

Fixtures include:

- `sample.mbox`
- `malformed.mbox`
- `large-mailbox.mbox`

`sample.mbox` covers two messages, a valid Message-ID, a reply with
`In-Reply-To` and `References`, multipart MIME metadata, an attachment stub,
safe `List-Unsubscribe` metadata, and fake redaction marker values.

MAIL2 also extends canonicalization fixtures under:

```text
src/test/fixtures/canonicalization/mail_basic/
```

The fixture corpus covers mailbox nodes, mailbox-to-message `defines` edges,
per-message MAIL1 observation reuse, MBOX ordinal metadata, malformed mailbox
diagnostics, limit diagnostics, redaction, and storage/readback safety.

Fixtures use fake values and reserved example domains only. They do not include
real email addresses, real personal names, private domains, private endpoints,
real tokens, real message bodies, or private correspondence.

## Storage And Readback

MAIL2 uses the existing storage path:

- raw observations are retained in `raw_observations`;
- generic `email.*` canonical nodes are stored in canonical graph tables;
- existing `defines` and `references` edges are used;
- public readback defaults are unchanged.

Useful readback examples:

```bash
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.mailbox --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.message --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.part --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.attachment_stub --json
repomap-kg storage nodes --root-path src/test/fixtures/discovery/mail_basic --kind email.thread_hint --json
repomap-kg storage edges --root-path src/test/fixtures/discovery/mail_basic --kind defines --json
repomap-kg storage edges --root-path src/test/fixtures/discovery/mail_basic --kind references --json
repomap-kg storage explain-canonical-edge --root-path src/test/fixtures/discovery/mail_basic --source-key '<email-mailbox-key>' --kind defines --target-key '<email-message-key>' --json
repomap-kg storage explain-canonical-edge --root-path src/test/fixtures/discovery/mail_basic --source-key '<email-message-key>' --kind references --target-key '<unknown-email-message-target>' --json
```

Storage tests verify mailbox nodes, contained message nodes, part/stub/thread
nodes, `defines` and `references` edges, mailbox-to-message explain output,
message reference explain output, and absence of raw full addresses, display
names, raw subjects, body text, attachment content, and fake secret marker
values in readback/explain output.

## Known Gaps

- Email readback polish and summary commands are deferred to MAIL3.
- `.mailbox` and extensionless mailbox discovery are deferred.
- Gmail Takeout/provider export auto-detection is deferred.
- Body URL extraction is deferred.
- Body text snippets and body-content nodes are deferred.
- Attachment content extraction, attachment parsing, OCR, archive opening, and
  macro decoding remain out of scope.
- Exact provider thread reconstruction is not attempted.
- Gmail, IMAP, SMTP, Microsoft Graph, OAuth, provider login, provider sync, and
  provider mutation are out of scope.
- BULK local corpus ingestion remains out of scope.

## Guardrail Confirmation

MAIL2 does not connect to Gmail, IMAP, SMTP, Microsoft Graph, or any provider,
prompt for credentials, use OAuth, mutate mailbox files or remote mailboxes,
send, forward, delete, archive, label, or mark mail read/unread, fetch remote
images, fetch tracking pixels, crawl links, fetch `Content-Location`, fetch or
resolve `cid:` references externally, execute HTML, render HTML, execute
JavaScript, execute attachments, parse attachment contents, OCR images, parse
PDFs, DOCX, XLSX, or archives, decode macros, store raw body text in canonical
metadata, store attachment bodies, expose raw full email addresses, display
names, or raw subjects in readback/explain, add provider namespaces, add MCP
tools, add storage migrations, change public readback defaults, implement BULK
behavior, or resume Phase F.
