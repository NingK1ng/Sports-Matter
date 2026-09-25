"""
Embedding生成服务

使用sentence-transformers生成文本向量（384维，all-MiniLM-L6-v2模型）
支持批量生成、缓存、错误重试
"""
import logging
from typing import List, Optional
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding生成服务（单例模式）"""
    
    _instance = None
    _model = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化embedding模型"""
        if self._model is None:
            # 懒加载：避免在未使用向量检索/Embedding功能时引入重量级依赖，
            # 也避免测试环境因 torch/torchvision 版本不匹配而在 import 阶段崩溃。
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
            except Exception as exc:  # pylint: disable=broad-except
                raise RuntimeError(
                    "sentence-transformers is required for EmbeddingService. "
                    "Install dependencies from requirements.txt"
                ) from exc

            logger.info("Loading sentence-transformers model: all-MiniLM-L6-v2...")
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("✅ Embedding model loaded successfully (384 dimensions)")
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        生成单个文本的embedding
        
        Args:
            text: 输入文本（标题或标题+摘要）
            
        Returns:
            384维的embedding向量，失败返回None
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding generation")
            return None
        
        try:
            # 生成embedding（返回numpy数组）
            embedding = self._model.encode(text.strip(), convert_to_numpy=True)
            
            # 转换为Python list
            return embedding.tolist()
        
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None
    
    def generate_embeddings_batch(
        self, 
        texts: List[str], 
        batch_size: int = 32,
        show_progress_bar: bool = True
    ) -> List[Optional[List[float]]]:
        """
        批量生成embedding（高效）
        
        Args:
            texts: 文本列表
            batch_size: 批次大小
            show_progress_bar: 是否显示进度条
            
        Returns:
            embedding列表，对应输入文本顺序
        """
        if not texts:
            return []
        
        try:
            # 批量编码（更高效）
            embeddings = self._model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=show_progress_bar,
                convert_to_numpy=True
            )
            
            # 转换为list格式
            return [emb.tolist() if emb is not None else None for emb in embeddings]
        
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            # 降级为逐个生成
            logger.warning("Falling back to individual embedding generation")
            return [self.generate_embedding(text) for text in texts]
    
    def generate_from_title_abstract(
        self, 
        title: str, 
        abstract: Optional[str] = None
    ) -> Optional[List[float]]:
        """
        从标题和摘要生成embedding
        
        Args:
            title: 文献标题
            abstract: 文献摘要（可选）
            
        Returns:
            384维embedding向量
        """
        # 拼接标题和摘要（标题权重更高）
        if abstract and abstract.strip():
            text = f"{title}. {abstract[:500]}"  # 限制摘要长度避免过长
        else:
            text = title
        
        return self.generate_embedding(text)
    
    @property
    def dimension(self) -> int:
        """返回embedding维度"""
        return 384
    
    @property
    def model_name(self) -> str:
        """返回模型名称"""
        return "all-MiniLM-L6-v2"


# 全局单例实例
@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """获取Embedding服务单例"""
    return EmbeddingService()
