"""Forge OS Layer 2: GRAPH — UUIDv8 deterministic identity system.

Port of the Cheeky UUIDv8 implementation (Kotlin) to Python.
Provides deterministic, time-ordered, content-addressable identifiers
for all Forge OS graph entities (conversations, threads, decisions,
lineage edges).

UUIDv8 (RFC 9562) format:
    [48-bit timestamp_ms] [4-bit version=8] [2-bit variant=10] [74-bit suffix]

Deterministic mode: suffix = SHA-256(namespace_bytes + timestamp_bytes)[:10]
Random mode: suffix = os.urandom(10)

Reference: cheekiverse-backend/.../uuid/UUIDv8.kt
"""

import hashlib
import os
import struct
import time
import uuid

# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

DNS_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

FORGE_OS_DNS = "forgeos.local"
BASE_UUID = uuid.uuid5(DNS_NAMESPACE, FORGE_OS_DNS)


# ---------------------------------------------------------------------------
# Core UUID functions
# ---------------------------------------------------------------------------

def v5(name: str, namespace: uuid.UUID | None = None) -> uuid.UUID:
    """Generate a UUIDv5 from a name string.

    Args:
        name: The input string to hash.
        namespace: UUID namespace. Defaults to FORGE_OS BASE_UUID.

    Returns:
        A deterministic UUIDv5.
    """
    if namespace is None:
        namespace = BASE_UUID
    return uuid.uuid5(namespace, name)


def v8(
    namespace: uuid.UUID | None = None,
    timestamp_ms: int | None = None,
    random: bool = False,
) -> uuid.UUID:
    """Generate a UUIDv8 (RFC 9562).

    Deterministic mode (default): suffix derived from SHA-256 of namespace
    and timestamp bytes. Same inputs always produce the same UUID.

    Random mode: cryptographically random suffix. Time-ordered but unique.

    Args:
        namespace: UUID namespace for deterministic derivation.
            Defaults to FORGE_OS BASE_UUID.
        timestamp_ms: Epoch milliseconds. Defaults to current time.
        random: If True, use random suffix instead of deterministic.

    Returns:
        A UUIDv8 with 48-bit timestamp prefix.
    """
    if namespace is None:
        namespace = BASE_UUID
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    # 1. First 6 bytes = timestamp in milliseconds (big-endian)
    #    Pack as 8-byte big-endian long, take last 6 bytes
    time_bytes = struct.pack(">Q", timestamp_ms)[2:]

    # 2. Suffix (10 bytes)
    if random:
        suffix = os.urandom(10)
    else:
        digest = hashlib.sha256()
        digest.update(namespace.bytes)
        digest.update(struct.pack(">Q", timestamp_ms))
        suffix = digest.digest()[:10]

    # 3. Combine: 6 bytes time + 10 bytes suffix = 16 bytes
    uuid_bytes = bytearray(time_bytes + suffix)

    # 4. Set version 8 (byte 6, high nibble = 1000)
    uuid_bytes[6] = (uuid_bytes[6] & 0x0F) | 0x80

    # 5. Set RFC 4122 variant (byte 8, high 2 bits = 10)
    uuid_bytes[8] = (uuid_bytes[8] & 0x3F) | 0x80

    return uuid.UUID(bytes=bytes(uuid_bytes))


def v8_from_string(
    name: str,
    namespace: uuid.UUID | None = None,
    timestamp_ms: int | None = None,
) -> uuid.UUID:
    """Generate a UUIDv8 from a string input.

    First derives a UUIDv5 namespace from the string, then generates
    a UUIDv8 using that derived namespace. Equivalent to the Kotlin
    overload: v8(fromString, timestamp).

    Args:
        name: Input string (e.g., conversation name, thread title).
        namespace: Base namespace for the v5 derivation.
            Defaults to FORGE_OS BASE_UUID.
        timestamp_ms: Epoch milliseconds. Defaults to current time.

    Returns:
        A deterministic UUIDv8 derived from the string + timestamp.
    """
    if namespace is None:
        namespace = BASE_UUID
    derived = uuid.uuid5(namespace, name)
    return v8(namespace=derived, timestamp_ms=timestamp_ms)


def composite_pair(a: uuid.UUID, b: uuid.UUID) -> uuid.UUID:
    """Order-independent pair ID.

    composite_pair(a, b) == composite_pair(b, a)

    Sorts the two UUIDs lexicographically, concatenates their string
    representations, and derives a UUIDv5. Used for lineage edges
    where the direction of discovery shouldn't affect the edge ID.

    Reference: UUID+Extensions.kt compositePair()

    Args:
        a: First UUID.
        b: Second UUID.

    Returns:
        A deterministic UUIDv5 that is the same regardless of argument order.
    """
    sorted_pair = sorted([a, b], key=str)
    name = str(sorted_pair[0]) + str(sorted_pair[1])
    return v5(name)


def parent_child(parent_id: uuid.UUID, child_id: uuid.UUID) -> uuid.UUID:
    """Directional composite ID encoding a parent-child relationship.

    Takes the first 8 bytes (most significant) from the parent and
    the last 8 bytes (least significant) from the child. Sets the
    RFC 4122 variant on byte 8.

    Unlike composite_pair, this IS order-dependent:
    parent_child(a, b) != parent_child(b, a)

    Reference: UUID+Extensions.kt parentChildUUID()

    Args:
        parent_id: The parent entity UUID.
        child_id: The child entity UUID.

    Returns:
        A composite UUID encoding the parent-child relationship.
    """
    composite = bytearray(16)
    composite[0:8] = parent_id.bytes[0:8]
    composite[8:16] = child_id.bytes[8:16]

    # Set RFC 4122 variant (byte 8, high 2 bits = 10)
    composite[8] = (composite[8] & 0x3F) | 0x80

    return uuid.UUID(bytes=bytes(composite))


# ---------------------------------------------------------------------------
# Forge OS entity ID derivation
# ---------------------------------------------------------------------------

def conversation_id(
    project_uuid: uuid.UUID,
    conversation_name: str,
    created_at_ms: int,
) -> uuid.UUID:
    """Derive a deterministic conversation ID.

    Args:
        project_uuid: The project's UUIDv8 namespace.
        conversation_name: The conversation's display name.
        created_at_ms: Creation timestamp in epoch milliseconds.

    Returns:
        UUIDv8 derived from project + name + timestamp.
    """
    return v8_from_string(
        name=conversation_name,
        namespace=project_uuid,
        timestamp_ms=created_at_ms,
    )


def project_id(project_name: str, created_at_ms: int) -> uuid.UUID:
    """Derive a deterministic project ID.

    Args:
        project_name: The project's display name (e.g., "The Nexus").
        created_at_ms: Creation timestamp in epoch milliseconds.

    Returns:
        UUIDv8 derived from BASE_UUID + name + timestamp.
    """
    return v8_from_string(
        name=project_name,
        namespace=BASE_UUID,
        timestamp_ms=created_at_ms,
    )


def thread_id(
    project_uuid: uuid.UUID,
    thread_title: str,
    first_seen_conversation_id: uuid.UUID,
) -> uuid.UUID:
    """Derive a deterministic thread ID.

    Thread IDs are content-addressable: the same thread discovered
    independently by two pipeline runs produces the same ID.

    Args:
        project_uuid: The project's UUIDv8 namespace.
        thread_title: The thread's title text.
        first_seen_conversation_id: UUID of the conversation
            where this thread first appeared.

    Returns:
        UUIDv8 derived from project + title + conversation.
    """
    content = thread_title + str(first_seen_conversation_id)
    derived = uuid.uuid5(project_uuid, content)
    # Use the first_seen_conversation's timestamp bits as the timestamp
    # by extracting the 48-bit prefix from the conversation ID
    ts_ms = _extract_timestamp(first_seen_conversation_id)
    return v8(namespace=derived, timestamp_ms=ts_ms)


def decision_id(
    project_uuid: uuid.UUID,
    decision_text: str,
    originated_conversation_id: uuid.UUID,
) -> uuid.UUID:
    """Derive a deterministic decision ID.

    Decision IDs are content-addressable: same decision text originating
    from the same conversation always produces the same ID. A revised
    decision gets a new ID (different text).

    Args:
        project_uuid: The project's UUIDv8 namespace.
        decision_text: The full decision statement.
        originated_conversation_id: UUID of the originating conversation.

    Returns:
        UUIDv8 derived from project + decision hash + conversation.
    """
    text_hash = hashlib.sha256(decision_text.encode("utf-8")).hexdigest()[:16]
    content = text_hash + str(originated_conversation_id)
    derived = uuid.uuid5(project_uuid, content)
    ts_ms = _extract_timestamp(originated_conversation_id)
    return v8(namespace=derived, timestamp_ms=ts_ms)


def lineage_id(
    source_conversation_id: uuid.UUID,
    target_conversation_id: uuid.UUID,
) -> uuid.UUID:
    """Derive a deterministic lineage edge ID.

    Order-independent: the same edge discovered from either direction
    produces the same ID, preventing duplicates.

    Args:
        source_conversation_id: The compressed conversation.
        target_conversation_id: The continuation conversation.

    Returns:
        A composite pair UUID for the lineage edge.
    """
    return composite_pair(source_conversation_id, target_conversation_id)


def compression_tag_id(
    project_uuid: uuid.UUID,
    conversation_id_val: uuid.UUID,
    compressed_at_ms: int,
    turn_start: int,
    turn_end: int,
) -> uuid.UUID:
    """Derive a deterministic compression tag ID.

    Args:
        project_uuid: The project's UUIDv8 namespace.
        conversation_id_val: The conversation being compressed.
        compressed_at_ms: Compression timestamp in epoch milliseconds.
        turn_start: First turn in the compressed range.
        turn_end: Last turn in the compressed range.

    Returns:
        UUIDv8 derived from project + conversation + turn range + timestamp.
    """
    content = f"{conversation_id_val}:{turn_start}-{turn_end}"
    derived = uuid.uuid5(project_uuid, content)
    return v8(namespace=derived, timestamp_ms=compressed_at_ms)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _extract_timestamp(uid: uuid.UUID) -> int:
    """Extract the 48-bit millisecond timestamp from a UUIDv8.

    If the UUID is not a v8 (no embedded timestamp), returns
    the current time as a fallback.

    Args:
        uid: A UUID, ideally UUIDv8 with an embedded timestamp.

    Returns:
        Epoch milliseconds extracted from the UUID's first 6 bytes.
    """
    uid_bytes = uid.bytes
    # Check if version is 8
    version = (uid_bytes[6] >> 4) & 0x0F
    if version != 8:
        return int(time.time() * 1000)

    # Extract 48-bit timestamp from first 6 bytes (big-endian)
    ts_ms = 0
    for i in range(6):
        ts_ms = (ts_ms << 8) | uid_bytes[i]
    return ts_ms


def extract_timestamp(uid: uuid.UUID) -> int:
    """Extract the 48-bit millisecond timestamp from a UUIDv8.

    Public wrapper around _extract_timestamp.

    Args:
        uid: A UUIDv8 with an embedded timestamp.

    Returns:
        Epoch milliseconds, or current time if not a v8 UUID.
    """
    return _extract_timestamp(uid)


def is_v8(uid: uuid.UUID) -> bool:
    """Check if a UUID has version 8.

    Args:
        uid: The UUID to check.

    Returns:
        True if the UUID's version nibble is 8.
    """
    return ((uid.bytes[6] >> 4) & 0x0F) == 8
