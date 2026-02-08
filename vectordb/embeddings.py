import voyageai

from vectordb.config import EMBEDDING_DIMENSIONS, VOYAGE_API_KEY, VOYAGE_BATCH_SIZE, VOYAGE_MODEL


def get_voyage_client():
    if not VOYAGE_API_KEY:
        raise RuntimeError(
            "VOYAGE_API_KEY not set. Export it before running:\n"
            "  export VOYAGE_API_KEY='your-key-here'"
        )
    return voyageai.Client(api_key=VOYAGE_API_KEY)


def embed_texts(texts, client=None, input_type="document"):
    """Embed a list of texts using VoyageAI, returning list of 1024-dim vectors.

    Automatically batches requests to stay within API limits.
    """
    if client is None:
        client = get_voyage_client()

    if not texts:
        return []

    all_embeddings = []
    for i in range(0, len(texts), VOYAGE_BATCH_SIZE):
        batch = texts[i : i + VOYAGE_BATCH_SIZE]
        result = client.embed(batch, model=VOYAGE_MODEL, input_type=input_type)
        all_embeddings.extend(result.embeddings)

    return all_embeddings


def embed_query(text, client=None):
    """Embed a single query text for search."""
    if client is None:
        client = get_voyage_client()

    result = client.embed([text], model=VOYAGE_MODEL, input_type="query")
    return result.embeddings[0]
