import os
import asyncio
from functools import partial
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from bioimageio_chatbot.knowledge_base import load_knowledge_base
from bioimageio_chatbot.utils import get_manifest
from bioimageio_chatbot.utils import ChatbotExtension


class DocWithScore(BaseModel):
    """A document with an associated relevance score."""

    doc: str = Field(description="The document retrieved.")
    score: float = Field(description="The relevance score of the retrieved document.")
    metadata: Dict[str, Any] = Field(description="The document's metadata.")
    base_url: Optional[str] = Field(
        None,
        description="The documentation's base URL, which will be used to resolve the relative URLs in the retrieved document chunks when producing markdown links.",
    )

class DocumentRetrievalInput(BaseModel):
    """Searching knowledge base for relevant documents."""
    query: str = Field(
        description="The query used to retrieve documents related to the user's request. Take preliminary_response as reference to generate query if needed."
    )
    top_k: int = Field(
        3,
        description="The maximum number of search results to return. Should use a small number to avoid overwhelming the user.",
    )

async def get_schema(channels):
    # create prompt for the list (markdown) of channels and its description
    channel_info = "\n".join(
        [
            f"- {channel['name']}: {channel['description']}"
            for channel in channels
        ]
    )
    DocumentRetrievalInput.__doc__ = f"""Searching knowledge base for relevant documents. The available documentations are:\n{channel_info}"""
    return DocumentRetrievalInput.schema()


async def run_extension(docs_store_dict, req):
    collections = get_manifest()["collections"]
    channel_results = []
    # limit top_k from 1 to 15
    req.top_k = max(1, min(req.top_k, 15))
    for channel_id in docs_store_dict:
        docs_store = docs_store_dict[channel_id]
        collection_info_dict = {collection["id"]: collection for collection in collections}
        collection_info = collection_info_dict[channel_id]
        base_url = collection_info.get("base_url")
        print(f"Retrieving documents from database {channel_id} with query: {req.query}")
        channel_results.append(docs_store.asimilarity_search_with_relevance_scores(
            req.query, k=req.top_k
        ))

    channel_results = await asyncio.gather(*channel_results)
    
        
    docs_with_score = [
        DocWithScore(
            doc=doc.page_content, score=score, metadata=doc.metadata, base_url=base_url
        )
        for results_with_scores in channel_results
        for doc, score in results_with_scores
    ]
    # sort by relevance score
    docs_with_score = sorted(docs_with_score, key=lambda x: x.score, reverse=True)[:req.top_k]
    
    if len(docs_with_score) > 0:
        print(
            f"Retrieved documents:\n{docs_with_score[0].doc[:20] + '...'} (score: {docs_with_score[0].score})\n{docs_with_score[1].doc[:20] + '...'} (score: {docs_with_score[1].score})\n{docs_with_score[2].doc[:20] + '...'} (score: {docs_with_score[2].score})"
        )
    return docs_with_score


def get_extensions():
    collections = get_manifest()["collections"]
    knowledge_base_path = os.environ.get("BIOIMAGEIO_KNOWLEDGE_BASE_PATH", "./bioimageio-knowledge-base")
    assert knowledge_base_path is not None, "Please set the BIOIMAGEIO_KNOWLEDGE_BASE_PATH environment variable to the path of the knowledge base."
    if not os.path.exists(knowledge_base_path):
        print(f"The knowledge base is not found at {knowledge_base_path}, will download it automatically.")
        os.makedirs(knowledge_base_path, exist_ok=True)
    
    knowledge_base_path = os.environ.get(
        "BIOIMAGEIO_KNOWLEDGE_BASE_PATH", "./bioimageio-knowledge-base"
    )
    docs_store_dict = load_knowledge_base(knowledge_base_path)
    return [ChatbotExtension(
        name="SearchInBioImageKnowledgeBase",
        description="""Search the BioImage Knowledge Base for relevant documentation.""",
        get_schema=partial(get_schema, collections),
        execute=partial(run_extension, docs_store_dict),
    )]
