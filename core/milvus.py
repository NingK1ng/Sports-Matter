"""
Milvus向量数据库客户端

提供向量索引和topK相似度检索功能
"""

from typing import List, Dict, Any, Optional

from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)

from core.config import settings


class MilvusConnectionError(Exception):
    """Milvus连接错误"""

    pass


# 全局连接状态
_milvus_connected = False


def init_milvus(host: str = "localhost", port: int = 19530) -> None:
    """
    初始化Milvus连接

    Args:
        host: Milvus服务地址
        port: Milvus gRPC端口

    Raises:
        MilvusConnectionError: 连接失败
    """
    global _milvus_connected

    if _milvus_connected:
        return  # 已连接

    try:
        connections.connect(
            alias="default",
            host=host,
            port=port,
        )

        _milvus_connected = True
        print("✅ Milvus向量数据库连接成功")
        print(f"   Host: {host}:{port}")

    except Exception as e:
        print(f"❌ Milvus连接失败: {e}")
        raise MilvusConnectionError(f"Failed to connect to Milvus: {e}")


def close_milvus() -> None:
    """
    关闭Milvus连接
    """
    global _milvus_connected

    if _milvus_connected:
        connections.disconnect("default")
        _milvus_connected = False
        print("👋 Milvus连接已关闭")


def is_connected() -> bool:
    """
    检查Milvus是否已连接

    Returns:
        bool: 连接状态
    """
    return _milvus_connected


def create_literature_collection(
    collection_name: str = "literature_embeddings",
    dim: int = 768,
) -> Collection:
    """
    创建文献向量集合

    Args:
        collection_name: 集合名称
        dim: 向量维度（默认768，BERT base）

    Returns:
        Collection: Milvus集合对象

    Example:
        collection = create_literature_collection()
    """
    if not _milvus_connected:
        raise RuntimeError("Milvus not connected. Call init_milvus() first.")

    # 定义Schema
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="pmid", dtype=DataType.INT64),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="文献向量集合")

    # 创建集合
    collection = Collection(collection_name, schema)

    # 创建索引
    index_params = {
        "metric_type": "L2",  # 欧氏距离
        "index_type": "IVF_FLAT",
        "params": {"nlist": 128},
    }
    collection.create_index("embedding", index_params)

    print(f"✅ Milvus集合创建成功: {collection_name}")
    return collection


def search_similar_literature(
    collection_name: str,
    query_embedding: List[float],
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    检索相似文献

    Args:
        collection_name: 集合名称
        query_embedding: 查询向量
        top_k: 返回前K个结果

    Returns:
        List[Dict]: 相似文献列表

    Example:
        results = search_similar_literature(
            "literature_embeddings",
            query_embedding,
            top_k=10
        )
    """
    if not _milvus_connected:
        raise RuntimeError("Milvus not connected. Call init_milvus() first.")

    collection = Collection(collection_name)
    collection.load()

    # 执行检索
    search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
    results = collection.search(
        data=[query_embedding],
        anns_field="embedding",
        param=search_params,
        limit=top_k,
        output_fields=["pmid"],
    )

    # 格式化结果
    similar_items = []
    for hit in results[0]:
        similar_items.append(
            {
                "pmid": hit.entity.get("pmid"),
                "distance": hit.distance,
                "score": 1 / (1 + hit.distance),  # 转换为相似度分数
            }
        )

    return similar_items
