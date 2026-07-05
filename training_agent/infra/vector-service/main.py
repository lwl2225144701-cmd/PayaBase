"""Vector Service.

Standalone service for text embedding using bge-small-zh-v1.5.
"""

import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # 强制使用CPU

import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 使用魔搭模型
from modelscope import snapshot_download
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = "AI-ModelScope/bge-small-zh-v1.5"  # 正确的modelscope模型ID
EMBEDDING_DIM = 512

model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup."""
    global model
    logger.info(f"Loading model: {MODEL_NAME}")
    
    # 使用modelscope下载模型
    try:
        model_dir = snapshot_download(MODEL_NAME, cache_dir='/root/.cache/modelscope')
        logger.info(f"Model downloaded to: {model_dir}")
        model = SentenceTransformer(model_dir)
    except Exception as e:
        logger.warning(f"ModelScope download failed: {e}, trying local cache")
        model = SentenceTransformer(MODEL_NAME)
    
    logger.info(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")
    yield
    logger.info("Shutting down vector service")


app = FastAPI(
    title="Vector Service",
    description="Text embedding service using bge-large-zh-v1.5",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class EmbedRequest(BaseModel):
    """Embedding request."""
    texts: List[str]
    normalize: bool = True
    batch_size: int = 32


class EmbedResponse(BaseModel):
    """Embedding response."""
    embeddings: List[List[float]]
    dimension: int
    count: int


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    if model is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "loading", "model": MODEL_NAME},
        )
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Embed texts into vectors.

    Args:
        request: Embed request with texts

    Returns:
        Embedding vectors
    """
    if model is None:
        raise RuntimeError("Model not loaded")

    embeddings = model.encode(
        request.texts,
        normalize_embeddings=request.normalize,
        batch_size=request.batch_size,
        show_progress_bar=len(request.texts) > 10,
    )

    return EmbedResponse(
        embeddings=embeddings.tolist(),
        dimension=EMBEDDING_DIM,
        count=len(request.texts),
    )


@app.post("/embed_single")
async def embed_single(text: str, normalize: bool = True):
    """Embed single text.

    Args:
        text: Text to embed
        normalize: Whether to normalize embedding

    Returns:
        Embedding vector
    """
    if model is None:
        raise RuntimeError("Model not loaded")

    embedding = model.encode(text, normalize_embeddings=normalize)

    return {
        "embedding": embedding.tolist(),
        "dimension": EMBEDDING_DIM,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)