import os
import uuid
from pathlib import Path
import tempfile

import voyageai
import chromadb
from chromadb.config import Settings
from langchain_anthropic import ChatAnthropic
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from app.config import get_settings
from app.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)

CHROMA_PATH = "/app/chroma_data"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
TOP_K = 5


def get_chroma_client() -> chromadb.Client:
    return chromadb.PersistentClient(
        path=CHROMA_PATH,
        settings=Settings(anonymized_telemetry=False),
    )


def get_voyage_client() -> voyageai.Client:
    return voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY", ""))


def get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        anthropic_api_key=settings.anthropic_api_key,
        max_tokens=1024,
    )


class RAGService:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.chroma = get_chroma_client()
        self.voyage = get_voyage_client()
        self.llm = get_llm()
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )

    def _get_collection(self):
        return self.chroma.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        result = self.voyage.embed(
            texts,
            model="voyage-3-lite",
            input_type="document",
        )
        return result.embeddings

    def _embed_query(self, text: str) -> list[float]:
        result = self.voyage.embed(
            [text],
            model="voyage-3-lite",
            input_type="query",
        )
        return result.embeddings[0]

    async def ingest_pdf(self, file_bytes: bytes, filename: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            loader = PyPDFLoader(tmp_path)
            pages = loader.load()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if not pages:
            raise ValueError("PDF appears to be empty or unreadable")

        chunks: list[Document] = self.splitter.split_documents(pages)
        if not chunks:
            raise ValueError("No text could be extracted from PDF")

        texts = [c.page_content for c in chunks]
        metadatas = [
            {
                "source": filename,
                "page": str(c.metadata.get("page", 0)),
                "chunk_index": str(i),
            }
            for i, c in enumerate(chunks)
        ]
        ids = [str(uuid.uuid4()) for _ in chunks]

        all_embeddings = []
        batch_size = 128
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_embeddings.extend(self._embed(batch))

        collection = self._get_collection()
        collection.add(
            documents=texts,
            embeddings=all_embeddings,
            metadatas=metadatas,
            ids=ids,
        )

        logger.info(
            "ingest_complete",
            collection=self.collection_name,
            filename=filename,
            chunks=len(chunks),
        )

        return {
            "filename": filename,
            "chunks_stored": len(chunks),
            "collection": self.collection_name,
        }

    async def query(self, question: str, trace_id: str = "") -> dict:
        collection = self._get_collection()

        count = collection.count()
        if count == 0:
            return {
                "answer": "No documents have been ingested yet. Please upload a PDF first.",
                "sources": [],
                "chunks_retrieved": 0,
            }

        query_embedding = self._embed_query(question)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(TOP_K, count),
            include=["documents", "metadatas", "distances"],
        )

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        context_parts = []
        sources = []
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances)):
            context_parts.append(f"[Source {i+1}] {doc}")
            sources.append({
                "source": meta.get("source", "unknown"),
                "page": meta.get("page", "0"),
                "relevance_score": round(1 - dist, 3),
            })

        context = "\n\n".join(context_parts)

        prompt = f"""You are a helpful assistant. Answer the question based on the provided context.
If the answer is not in the context, say so clearly.

Context:
{context}

Question: {question}

Answer:"""

        response = self.llm.invoke(prompt)
        answer = response.content

        logger.info(
            "query_complete",
            collection=self.collection_name,
            chunks_retrieved=len(docs),
            trace_id=trace_id,
        )

        return {
            "answer": answer,
            "sources": sources,
            "chunks_retrieved": len(docs),
        }