"""Text chunking for Forge OS Layer 1: MEMORY document embeddings."""


def chunk_text(text, chunk_size=1000, overlap=200):
    """Split text into overlapping chunks at paragraph boundaries.

    Args:
        text: Source text to chunk.
        chunk_size: Target characters per chunk.
        overlap: Character overlap between consecutive chunks.

    Returns:
        List of dicts: [{"chunk_text": str, "chunk_index": int}]
    """
    if not text or not text.strip():
        return []

    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    chunk_index = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        candidate = (
            f"{current_chunk}\n\n{paragraph}" if current_chunk else paragraph
        )

        if len(candidate) > chunk_size and current_chunk:
            chunks.append({
                "chunk_text": current_chunk.strip(),
                "chunk_index": chunk_index,
            })
            chunk_index += 1

            # Start next chunk with overlap from the end of current
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:] + "\n\n" + paragraph
            else:
                current_chunk = paragraph
        else:
            current_chunk = candidate

    # Flush remaining content
    if current_chunk.strip():
        chunks.append({
            "chunk_text": current_chunk.strip(),
            "chunk_index": chunk_index,
        })

    # Add total_chunks to each entry
    total = len(chunks)
    for chunk in chunks:
        chunk["total_chunks"] = total

    return chunks
