"""Rerank Service.

使用ModelScope的bge-reranker模型进行结果重排序。
"""

import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''

import logging
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 使用ModelScope模型
MODEL_NAME = "BAAI/bge-reranker-base"

model = None


def load_model():
    """Load reranker model from ModelScope."""
    global model
    logger.info(f"Loading model: {MODEL_NAME}")
    
    try:
        from modelscope import snapshot_download
        from sentence_transformers import CrossEncoder
        
        # 从ModelScope下载模型
        model_dir = snapshot_download(MODEL_NAME, cache_dir='/root/.cache/modelscope')
        logger.info(f"Model downloaded to: {model_dir}")
        
        model = CrossEncoder(model_dir)
        logger.info("Reranker model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise


class RerankRequest(BaseModel):
    """Rerank request."""
    query: str
    texts: List[str]
    top_k: int = 5


class RerankResponse(BaseModel):
    """Rerank response."""
    results: List[int]
    scores: List[float]


app = FastAPI(
    title="Rerank Service",
    description="bge-reranker重排序服务",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    load_model()


@app.get("/health")
async def health_check():
    """Health check."""
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/rerank", response_model=RerankResponse)
async def rerank(request: RerankRequest):
    """Re-rank texts."""
    if model is None:
        raise RuntimeError("Model not loaded")
    
    pairs = [[request.query, text] for text in request.texts]
    scores = model.predict(pairs)
    
    ranked_indices = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True,
    )
    
    top_indices = ranked_indices[:request.top_k]
    top_scores = [float(scores[i]) for i in top_indices]
    
    return RerankResponse(
        results=top_indices,
        scores=top_scores,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)