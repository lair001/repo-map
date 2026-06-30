"""Static local RSS, Atom, and JSON Feed extraction."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from repomap_kg.graph_keys import (
    dynamic_key,
    external_key,
    external_url_key,
    feed_author_key,
    feed_category_key,
    feed_channel_key,
    feed_document_key,
    feed_item_key,
    file_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


EXTRACTOR_NAME = "repo-feed"
EXTRACTOR_VERSION = "0.1.0"
FEED_XML_SAFETY_MODE = "stdlib-elementtree-prescan-no-external-entities"
JSON_FEED_PARSER = "stdlib-json-local-feed-shape"
SAFE_SUMMARY_LIMIT = 160

UNSAFE_XML_DECLARATION_PATTERN = re.compile(
    r"<!\s*(?:DOCTYPE|ENTITY)\b",
    re.IGNORECASE,
)
UNSAFE_PROCESSING_INSTRUCTION_PATTERN = re.compile(
    r"<\?(?!xml(?:\s|\?>))",
    re.IGNORECASE,
)
FEED_ROOT_PATTERN = re.compile(r"<\s*(?:rss|feed)(?:\s|>|/)", re.IGNORECASE)
TAG_PATTERN = re.compile(r"<[^>]+>")
SCRIPT_STYLE_PATTERN = re.compile(
    r"<\s*(script|style)\b.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
WHITESPACE_PATTERN = re.compile(r"\s+")
DYNAMIC_REFERENCE_PATTERN = re.compile(r"(\$[A-Za-z_][A-Za-z0-9_]*|\$\{|{{|}}|[*?])")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "access_key",
    "refresh_token",
    "bearer",
    "auth",
)


def extract_feed_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    """Extract feed observations from a local RSS, Atom, or JSON Feed artifact."""
    if _looks_like_feed_xml(content):
        return _extract_xml_feed(relative_path, content)
    json_payload = _parse_json_feed_payload(content)
    if json_payload is None:
        return ()
    return _extract_json_feed(relative_path, json_payload)


def _extract_xml_feed(relative_path: str, content: str) -> tuple[RawObservation, ...]:
    if UNSAFE_XML_DECLARATION_PATTERN.search(content):
        return (
            _parse_error_observation(
                relative_path,
                "unsafe-xml-declaration",
                "feed XML contains a DOCTYPE or ENTITY declaration",
            ),
        )
    if UNSAFE_PROCESSING_INSTRUCTION_PATTERN.search(content):
        return (
            _parse_error_observation(
                relative_path,
                "unsafe-processing-instruction",
                "feed XML contains a non-XML processing instruction",
            ),
        )
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        return (
            _parse_error_observation(
                relative_path,
                "xml-parse-error",
                str(error),
            ),
        )

    root_name = _local_name(root.tag)
    if root_name == "rss":
        return _extract_rss(relative_path, root)
    if root_name == "feed":
        return _extract_atom(relative_path, root)
    return ()


def _extract_rss(relative_path: str, root: ElementTree.Element) -> tuple[RawObservation, ...]:
    channel = _first_child(root, "channel")
    if channel is None:
        return (
            _parse_error_observation(
                relative_path,
                "rss-missing-channel",
                "RSS feed is missing a channel element",
            ),
        )
    document_key = feed_document_key(relative_path)
    channel_info = _rss_channel_info(relative_path, document_key, channel)
    observations = [
        _feed_document_observation(
            relative_path,
            feed_format="rss",
            document_key=document_key,
            top_level_type="rss",
        ),
        _feed_channel_observation(relative_path, channel_info),
    ]
    channel_link = _child_text(channel, "link")
    if channel_link:
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=channel_info["channel_key"],
                raw_target=channel_link,
                target=_reference_target(relative_path, channel_link),
                source_id=f"{relative_path}#feed-channel-link",
                name=channel_link,
                metadata={
                    "feed_format": "rss",
                    "scope": "channel",
                    "attribute": "link",
                    "not_fetched": True,
                },
            )
        )

    items = [_rss_item_data(relative_path, channel_info["channel_key"], item, index) for index, item in enumerate(_children(channel, "item"), start=1)]
    observations.extend(_item_observations(relative_path, "rss", channel_info["channel_key"], items))
    return tuple(observations)


def _extract_atom(relative_path: str, root: ElementTree.Element) -> tuple[RawObservation, ...]:
    document_key = feed_document_key(relative_path)
    channel_info = _atom_channel_info(relative_path, document_key, root)
    observations = [
        _feed_document_observation(
            relative_path,
            feed_format="atom",
            document_key=document_key,
            top_level_type="atom",
        ),
        _feed_channel_observation(relative_path, channel_info),
    ]
    for link in _children(root, "link"):
        href = link.attrib.get("href", "").strip()
        if not href:
            continue
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=channel_info["channel_key"],
                raw_target=href,
                target=_reference_target(relative_path, href),
                source_id=f"{relative_path}#feed-channel-link:{len(observations)}",
                name=href,
                metadata={
                    "feed_format": "atom",
                    "scope": "channel",
                    "attribute": "href",
                    "rel": link.attrib.get("rel", "alternate"),
                    "not_fetched": True,
                },
            )
        )

    entries = [
        _atom_item_data(relative_path, channel_info["channel_key"], entry, index)
        for index, entry in enumerate(_children(root, "entry"), start=1)
    ]
    observations.extend(_item_observations(relative_path, "atom", channel_info["channel_key"], entries))
    return tuple(observations)


def _extract_json_feed(
    relative_path: str,
    payload: dict[str, Any],
) -> tuple[RawObservation, ...]:
    document_key = feed_document_key(relative_path)
    channel_info = _json_channel_info(relative_path, document_key, payload)
    observations = [
        _feed_document_observation(
            relative_path,
            feed_format="json-feed",
            document_key=document_key,
            top_level_type="object",
        ),
        _feed_channel_observation(relative_path, channel_info),
    ]
    for field in ("feed_url", "home_page_url"):
        value = _text_value(payload.get(field))
        if value is None:
            continue
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=channel_info["channel_key"],
                raw_target=value,
                target=_reference_target(relative_path, value),
                source_id=f"{relative_path}#feed-channel-link:{field}",
                name=value,
                metadata={
                    "feed_format": "json-feed",
                    "scope": "channel",
                    "field": field,
                    "not_fetched": True,
                },
            )
        )

    items = [
        _json_item_data(relative_path, channel_info["channel_key"], item, index)
        for index, item in enumerate(payload.get("items", []), start=1)
        if isinstance(item, dict)
    ]
    observations.extend(_item_observations(relative_path, "json-feed", channel_info["channel_key"], items))
    return tuple(observations)


def _item_observations(
    relative_path: str,
    feed_format: str,
    channel_key: str,
    items: list[dict[str, Any]],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    counts: dict[str, int] = {}
    for item in items:
        counts[item["base_item_id"]] = counts.get(item["base_item_id"], 0) + 1
    seen: dict[str, int] = {}
    for item in items:
        base_item_id = item["base_item_id"]
        seen[base_item_id] = seen.get(base_item_id, 0) + 1
        duplicate_identity = counts[base_item_id] > 1
        if duplicate_identity:
            item_id = f"{base_item_id}:duplicate-{seen[base_item_id]}"
        else:
            item_id = base_item_id
        item_key = feed_item_key(channel_key, item_id)
        item_metadata = {
            key: value
            for key, value in item["metadata"].items()
            if value is not None
        }
        item_metadata["channel_key"] = channel_key
        item_metadata["identity_source"] = item["identity_source"]
        item_metadata["identity_strength"] = item["identity_strength"]
        if duplicate_identity:
            item_metadata["duplicate_identity"] = True
            item_metadata["duplicate_disambiguator"] = f"duplicate-{seen[base_item_id]}"
        observations.append(
            _obs(
                kind="feed.item",
                source_id=f"{relative_path}#feed-item:{item['ordinal']}",
                path=relative_path,
                target=item_key,
                name=item.get("title") or item_id,
                confidence="extracted",
                metadata=item_metadata,
            )
        )
        observations.extend(
            _item_reference_observations(
                relative_path,
                feed_format,
                item_key,
                item,
            )
        )
    return observations


def _item_reference_observations(
    relative_path: str,
    feed_format: str,
    item_key: str,
    item: dict[str, Any],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for index, link in enumerate(item["links"], start=1):
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=item_key,
                raw_target=link["value"],
                target=_reference_target(relative_path, link["value"]),
                source_id=f"{relative_path}#feed-item:{item['ordinal']}:link:{index}",
                name=link["value"],
                metadata={
                    "feed_format": feed_format,
                    "scope": "item",
                    "attribute": link.get("attribute", "link"),
                    "rel": link.get("rel"),
                    "not_fetched": True,
                },
            )
        )
    for index, enclosure in enumerate(item["enclosures"], start=1):
        observations.append(
            _reference_observation(
                kind="feed.enclosure",
                relative_path=relative_path,
                source_key=item_key,
                raw_target=enclosure["url"],
                target=_reference_target(relative_path, enclosure["url"]),
                source_id=f"{relative_path}#feed-item:{item['ordinal']}:enclosure:{index}",
                name=enclosure["url"],
                metadata={
                    "feed_format": feed_format,
                    "scope": "item",
                    "attribute": enclosure.get("attribute", "url"),
                    "mime_type": enclosure.get("mime_type"),
                    "length": enclosure.get("length"),
                    "not_fetched": True,
                },
            )
        )
    for index, author in enumerate(item["authors"], start=1):
        observations.append(
            _feed_author_observation(
                relative_path,
                channel_key=item["channel_key"],
                item_key=item_key,
                feed_format=feed_format,
                ordinal=item["ordinal"],
                index=index,
                author=author,
            )
        )
    for index, category in enumerate(item["categories"], start=1):
        observations.append(
            _feed_category_observation(
                relative_path,
                channel_key=item["channel_key"],
                item_key=item_key,
                feed_format=feed_format,
                ordinal=item["ordinal"],
                index=index,
                category=category,
            )
        )
    if item.get("content"):
        observations.append(
            _feed_content_observation(
                relative_path,
                item_key=item_key,
                feed_format=feed_format,
                ordinal=item["ordinal"],
                content=item["content"],
                content_kind=item["content_kind"],
            )
        )
    return observations


def _rss_channel_info(
    relative_path: str,
    document_key: str,
    channel: ElementTree.Element,
) -> dict[str, Any]:
    title = _child_text(channel, "title")
    link = _child_text(channel, "link")
    if link:
        channel_id = f"link:{link}"
        identity_source = "link"
        identity_strength = "strong"
    elif title:
        channel_id = f"title:{_slug(title)}:{document_key}"
        identity_source = "title+document"
        identity_strength = "weak"
    else:
        channel_id = "self"
        identity_source = "document"
        identity_strength = "structural"
    return _channel_info(
        relative_path,
        document_key,
        channel_id,
        title,
        "rss",
        identity_source,
        identity_strength,
    )


def _atom_channel_info(
    relative_path: str,
    document_key: str,
    feed: ElementTree.Element,
) -> dict[str, Any]:
    title = _child_text(feed, "title")
    self_link = _atom_link(feed, "self")
    feed_id = _child_text(feed, "id")
    alternate_link = _atom_link(feed, "alternate")
    if self_link:
        channel_id = f"self:{self_link}"
        identity_source = "self-link"
        identity_strength = "strong"
    elif feed_id:
        channel_id = f"id:{feed_id}"
        identity_source = "id"
        identity_strength = "strong"
    elif alternate_link:
        channel_id = f"link:{alternate_link}"
        identity_source = "link"
        identity_strength = "strong"
    elif title:
        channel_id = f"title:{_slug(title)}:{document_key}"
        identity_source = "title+document"
        identity_strength = "weak"
    else:
        channel_id = "self"
        identity_source = "document"
        identity_strength = "structural"
    return _channel_info(
        relative_path,
        document_key,
        channel_id,
        title,
        "atom",
        identity_source,
        identity_strength,
        updated_at=_parse_date(_child_text(feed, "updated")),
    )


def _json_channel_info(
    relative_path: str,
    document_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    title = _text_value(payload.get("title"))
    feed_url = _text_value(payload.get("feed_url"))
    home_page_url = _text_value(payload.get("home_page_url"))
    if feed_url:
        channel_id = f"self:{feed_url}"
        identity_source = "feed_url"
        identity_strength = "strong"
    elif home_page_url:
        channel_id = f"link:{home_page_url}"
        identity_source = "home_page_url"
        identity_strength = "strong"
    elif title:
        channel_id = f"title:{_slug(title)}:{document_key}"
        identity_source = "title+document"
        identity_strength = "weak"
    else:
        channel_id = "self"
        identity_source = "document"
        identity_strength = "structural"
    return _channel_info(
        relative_path,
        document_key,
        channel_id,
        title,
        "json-feed",
        identity_source,
        identity_strength,
    )


def _channel_info(
    relative_path: str,
    document_key: str,
    channel_id: str,
    title: str | None,
    feed_format: str,
    identity_source: str,
    identity_strength: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    channel_key = feed_channel_key(document_key, channel_id)
    return {
        "channel_key": channel_key,
        "document_key": document_key,
        "title": title,
        "feed_format": feed_format,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "updated_at": updated_at,
        "relative_path": relative_path,
    }


def _rss_item_data(
    relative_path: str,
    channel_key: str,
    item: ElementTree.Element,
    ordinal: int,
) -> dict[str, Any]:
    title = _child_text(item, "title")
    link = _child_text(item, "link")
    guid = _child_text(item, "guid")
    pub_date = _child_text(item, "pubDate")
    base_item_id, identity_source, identity_strength = _item_identity(
        ("guid", guid),
        ("link", link),
        ("title+pubDate", _title_date_identity(title, pub_date)),
        ordinal=ordinal,
    )
    enclosures = []
    for enclosure in _children(item, "enclosure"):
        url = enclosure.attrib.get("url", "").strip()
        if not url:
            continue
        enclosures.append(
            {
                "url": url,
                "mime_type": enclosure.attrib.get("type"),
                "length": enclosure.attrib.get("length"),
                "attribute": "url",
            }
        )
    author = _rss_author(_child_text(item, "author"))
    authors = [author] if author else []
    categories = [_safe_label(_element_text(category)) for category in _children(item, "category")]
    content = _child_text(item, "description") or _child_text(item, "encoded")
    return {
        "ordinal": ordinal,
        "channel_key": channel_key,
        "base_item_id": base_item_id,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "title": title,
        "links": [{"value": link, "attribute": "link"}] if link else [],
        "enclosures": enclosures,
        "authors": [author for author in authors if author],
        "categories": [category for category in categories if category],
        "content": content,
        "content_kind": "description",
        "metadata": {
            "feed_format": "rss",
            "title": _safe_summary(title),
            "published_at": _parse_date(pub_date),
        },
    }


def _atom_item_data(
    relative_path: str,
    channel_key: str,
    entry: ElementTree.Element,
    ordinal: int,
) -> dict[str, Any]:
    title = _child_text(entry, "title")
    entry_id = _child_text(entry, "id")
    alternate_link = _atom_link(entry, "alternate")
    updated = _child_text(entry, "updated")
    published = _child_text(entry, "published")
    base_item_id, identity_source, identity_strength = _item_identity(
        ("id", entry_id),
        ("alternate-link", alternate_link),
        ("title+updated", _title_date_identity(title, updated or published)),
        ordinal=ordinal,
    )
    links = []
    for link in _children(entry, "link"):
        href = link.attrib.get("href", "").strip()
        if href:
            links.append(
                {
                    "value": href,
                    "attribute": "href",
                    "rel": link.attrib.get("rel", "alternate"),
                }
            )
    authors = []
    for author in _children(entry, "author"):
        name = _child_text(author, "name")
        uri = _child_text(author, "uri")
        authors.append({"name": _safe_label(name or uri or "unknown-author")})
    categories = [
        _safe_label(category.attrib.get("term") or category.attrib.get("label"))
        for category in _children(entry, "category")
    ]
    content = _child_text(entry, "summary") or _child_text(entry, "content")
    return {
        "ordinal": ordinal,
        "channel_key": channel_key,
        "base_item_id": base_item_id,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "title": title,
        "links": links,
        "enclosures": [],
        "authors": [author for author in authors if author.get("name")],
        "categories": [category for category in categories if category],
        "content": content,
        "content_kind": "summary",
        "metadata": {
            "feed_format": "atom",
            "title": _safe_summary(title),
            "updated_at": _parse_date(updated),
            "published_at": _parse_date(published),
        },
    }


def _json_item_data(
    relative_path: str,
    channel_key: str,
    item: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    title = _text_value(item.get("title"))
    url = _text_value(item.get("url"))
    external_url = _text_value(item.get("external_url"))
    published = _text_value(item.get("date_published"))
    modified = _text_value(item.get("date_modified"))
    base_item_id, identity_source, identity_strength = _item_identity(
        ("id", _text_value(item.get("id"))),
        ("url", url or external_url),
        ("title+date", _title_date_identity(title, published or modified)),
        ordinal=ordinal,
    )
    links = []
    for field, value in (("url", url), ("external_url", external_url)):
        if value:
            links.append({"value": value, "attribute": field})
    enclosures = []
    for attachment in item.get("attachments", []):
        if not isinstance(attachment, dict):
            continue
        attachment_url = _text_value(attachment.get("url"))
        if attachment_url:
            enclosures.append(
                {
                    "url": attachment_url,
                    "mime_type": _text_value(attachment.get("mime_type")),
                    "length": attachment.get("size_in_bytes"),
                    "attribute": "url",
                }
            )
    authors = []
    for author in item.get("authors", []):
        if isinstance(author, dict):
            name = _text_value(author.get("name")) or _text_value(author.get("url"))
            if name:
                authors.append({"name": _safe_label(name)})
    categories = [_safe_label(tag) for tag in item.get("tags", []) if isinstance(tag, str)]
    content = (
        _text_value(item.get("summary"))
        or _text_value(item.get("content_text"))
        or _text_value(item.get("content_html"))
    )
    return {
        "ordinal": ordinal,
        "channel_key": channel_key,
        "base_item_id": base_item_id,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "title": title,
        "links": links,
        "enclosures": enclosures,
        "authors": authors,
        "categories": [category for category in categories if category],
        "content": content,
        "content_kind": "content",
        "metadata": {
            "feed_format": "json-feed",
            "title": _safe_summary(title),
            "published_at": _parse_date(published),
            "updated_at": _parse_date(modified),
        },
    }


def _feed_document_observation(
    relative_path: str,
    *,
    feed_format: str,
    document_key: str,
    top_level_type: str,
) -> RawObservation:
    return _obs(
        kind="feed.document",
        source_id=f"{relative_path}#feed-document",
        path=relative_path,
        target=document_key,
        name=relative_path,
        confidence="extracted",
        metadata={
            "feed_format": feed_format,
            "parser": EXTRACTOR_NAME,
            "parser_mode": FEED_XML_SAFETY_MODE if feed_format in ("rss", "atom") else JSON_FEED_PARSER,
            "top_level_type": top_level_type,
        },
    )


def _feed_channel_observation(relative_path: str, channel_info: dict[str, Any]) -> RawObservation:
    metadata = {
        "feed_format": channel_info["feed_format"],
        "document_key": channel_info["document_key"],
        "identity_source": channel_info["identity_source"],
        "identity_strength": channel_info["identity_strength"],
        "title": _safe_summary(channel_info.get("title")),
        "updated_at": channel_info.get("updated_at"),
    }
    return _obs(
        kind="feed.channel",
        source_id=f"{relative_path}#feed-channel",
        path=relative_path,
        target=channel_info["channel_key"],
        name=channel_info.get("title") or relative_path,
        confidence="extracted",
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _feed_author_observation(
    relative_path: str,
    *,
    channel_key: str,
    item_key: str,
    feed_format: str,
    ordinal: int,
    index: int,
    author: dict[str, Any],
) -> RawObservation:
    name = _safe_label(author.get("name")) or "unknown-author"
    return _obs(
        kind="feed.author",
        source_id=f"{relative_path}#feed-item:{ordinal}:author:{index}",
        path=relative_path,
        target=feed_author_key(channel_key, name),
        name=name,
        confidence="extracted",
        metadata={
            "feed_format": feed_format,
            "channel_key": channel_key,
            "item_key": item_key,
            "name": name,
            "email_redacted": bool(author.get("email_redacted")),
        },
    )


def _feed_category_observation(
    relative_path: str,
    *,
    channel_key: str,
    item_key: str,
    feed_format: str,
    ordinal: int,
    index: int,
    category: str,
) -> RawObservation:
    label = _safe_label(category) or "unknown-category"
    return _obs(
        kind="feed.category",
        source_id=f"{relative_path}#feed-item:{ordinal}:category:{index}",
        path=relative_path,
        target=feed_category_key(channel_key, label),
        name=label,
        confidence="extracted",
        metadata={
            "feed_format": feed_format,
            "channel_key": channel_key,
            "item_key": item_key,
            "name": label,
        },
    )


def _feed_content_observation(
    relative_path: str,
    *,
    item_key: str,
    feed_format: str,
    ordinal: int,
    content: str,
    content_kind: str,
) -> RawObservation:
    summary = _safe_summary(content)
    redacted = summary is None and bool(content)
    metadata: dict[str, Any] = {
        "feed_format": feed_format,
        "item_key": item_key,
        "content_kind": content_kind,
        "content_policy": "summarized-not-rendered",
        "redacted": redacted,
        "original_length": len(content),
    }
    if summary is not None:
        metadata["value_summary"] = summary
    if redacted:
        metadata["redaction_reason"] = "secret-prone-content"
    return _obs(
        kind="feed.content",
        source_id=f"{relative_path}#feed-item:{ordinal}:content",
        path=relative_path,
        confidence="extracted",
        metadata=metadata,
    )


def _reference_observation(
    *,
    kind: str,
    relative_path: str,
    source_key: str,
    raw_target: str,
    target: str,
    source_id: str,
    name: str,
    metadata: dict[str, Any],
) -> RawObservation:
    safe_metadata = {
        key: value for key, value in metadata.items() if value is not None
    }
    safe_metadata["source_key"] = source_key
    safe_metadata["raw_target_summary"] = _safe_summary(raw_target)
    safe_metadata["target_kind"] = target.partition(":")[0]
    return _obs(
        kind=kind,
        source_id=source_id,
        path=relative_path,
        target=target,
        name=name,
        confidence="extracted",
        metadata=safe_metadata,
    )


def _parse_error_observation(
    relative_path: str,
    error_kind: str,
    message: str,
) -> RawObservation:
    return _obs(
        kind="feed.parse_error",
        source_id=f"{relative_path}#feed-parse-error:{error_kind}",
        path=relative_path,
        confidence="unknown",
        metadata={
            "feed_format": "unknown",
            "error_kind": error_kind,
            "message": _safe_summary(message) or error_kind,
            "raw_only": True,
        },
    )


def _obs(
    *,
    kind: str,
    source_id: str,
    path: str,
    confidence: str,
    metadata: dict[str, Any],
    name: str | None = None,
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=path,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        name=name,
        target=target,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _parse_json_feed_payload(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if not _is_json_feed_payload(payload):
        return None
    return payload


def _is_json_feed_payload(payload: dict[str, Any]) -> bool:
    version = payload.get("version")
    title = payload.get("title")
    items = payload.get("items")
    return (
        isinstance(version, str)
        and "jsonfeed" in version.lower()
        and isinstance(title, str)
        and isinstance(items, list)
    )


def _looks_like_feed_xml(content: str) -> bool:
    return bool(FEED_ROOT_PATTERN.search(content))


def _item_identity(
    *candidates: tuple[str, str | None],
    ordinal: int,
) -> tuple[str, str, str]:
    for source, value in candidates:
        if value:
            strength = "weak" if source.startswith("title+") else "strong"
            return f"{source}:{value}", source, strength
    return f"ordinal:{ordinal}", "structural-ordinal", "structural"


def _title_date_identity(title: str | None, date_text: str | None) -> str | None:
    if not title or not date_text:
        return None
    normalized = _parse_date(date_text) or _collapse_text(date_text)
    return f"{_slug(title)}:{normalized}"


def _reference_target(relative_path: str, raw_target: str) -> str:
    value = raw_target.strip()
    if not value:
        return unknown_key("feed.reference", "missing-target")
    if DYNAMIC_REFERENCE_PATTERN.search(value) or value.startswith("~"):
        return dynamic_key("file", "feed-reference-expanded-from-variable")
    parsed = urlsplit(value)
    if parsed.scheme:
        scheme = parsed.scheme.lower()
        if scheme in ("http", "https"):
            if parsed.netloc:
                return external_url_key(value)
            return unknown_key("external.url", "malformed-feed-reference")
        if scheme == "mailto":
            return external_url_key(value)
        return dynamic_key("url", "unsupported-url-scheme")
    if value.startswith("/"):
        return external_key("file", "absolute-feed-reference")
    source_parent = PurePosixPath(relative_path).parent
    target_path = (source_parent / value).as_posix()
    try:
        return file_key(target_path)
    except Exception:
        return unknown_key("file", "repo-escaping-feed-reference")


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_summary(value: str | None) -> str | None:
    if value is None:
        return None
    if _contains_secret_marker(value):
        return None
    text = _collapse_text(_strip_html(value))
    if not text:
        return None
    if len(text) > SAFE_SUMMARY_LIMIT:
        return text[: SAFE_SUMMARY_LIMIT - 1].rstrip() + "..."
    return text


def _safe_label(value: str | None) -> str | None:
    summary = _safe_summary(value)
    if summary is None:
        return None
    return summary


def _strip_html(value: str) -> str:
    without_script = SCRIPT_STYLE_PATTERN.sub(" ", value)
    return TAG_PATTERN.sub(" ", without_script)


def _collapse_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _contains_secret_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _slug(value: str) -> str:
    text = _collapse_text(_strip_html(value)).lower()
    parts = []
    previous_dash = False
    for character in text:
        if character.isalnum():
            parts.append(character)
            previous_dash = False
        elif not previous_dash:
            parts.append("-")
            previous_dash = True
    slug = "".join(parts).strip("-")
    return slug or "untitled"


def _rss_author(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    text = _collapse_text(value)
    match = re.search(r"\(([^)]+)\)", text)
    name = match.group(1) if match else text
    if EMAIL_PATTERN.match(name):
        return {"name": "redacted-author", "email_redacted": True}
    if "@" in text:
        return {"name": _safe_label(name), "email_redacted": True}
    return {"name": _safe_label(name)}


def _atom_link(parent: ElementTree.Element, rel: str) -> str | None:
    fallback = None
    for link in _children(parent, "link"):
        href = link.attrib.get("href", "").strip()
        if not href:
            continue
        link_rel = link.attrib.get("rel", "alternate")
        if link_rel == rel:
            return href
        if link_rel == "alternate":
            fallback = href
    if rel == "alternate":
        return fallback
    return None


def _text_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for child in parent:
        if _local_name(child.tag) == name:
            return child
    return None


def _children(parent: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in parent if _local_name(child.tag) == name]


def _child_text(parent: ElementTree.Element, name: str) -> str | None:
    child = _first_child(parent, name)
    if child is None:
        return None
    return _element_text(child)


def _element_text(element: ElementTree.Element) -> str | None:
    text = "".join(element.itertext())
    text = _collapse_text(text)
    return text or None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag
