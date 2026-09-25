"""
LLM文献分类服务（DeepSeek）
使用标题+摘要前100字，批处理降低成本
"""
import asyncio
import os
from typing import List, Dict, Any
import httpx
import json
from dotenv import load_dotenv

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model

# 加载环境变量
load_dotenv()


class LLMClassifier:
    """LLM文献分类器"""
    
    # 8个学科类别定义
    CATEGORIES = {
        "sports_education": "体育教育",
        "training_science": "运动训练",
        "fitness_monitoring": "体质健康与监测",
        "exercise_science": "运动基础科学",
        "sports_medicine": "运动医学与康复",
        "sport_psychology": "运动心理",
        "sport_humanities": "体育人文与社会科学",
        "sport_engineering": "体育工程与技术"
    }
    
    # 类别详细说明
    CATEGORY_DESCRIPTIONS = {
        "sports_education": "体育教学、课程设计、教师培训、学校体育",
        "training_science": "运动训练方法、竞技表现、技战术、专项训练",
        "fitness_monitoring": "体质测试、健康监测、可穿戴设备、运动处方",
        "exercise_science": "运动生理、生物力学、运动营养、运动生化",
        "sports_medicine": "运动损伤、康复治疗、运动防护、临床医学",
        "sport_psychology": "运动心理、动机、情绪、心理技能",
        "sport_humanities": "体育社会学、体育经济、体育政策、体育文化",
        "sport_engineering": "运动装备、场地设施、运动技术、数据分析"
    }
    
    def __init__(self, api_key: str = None):
        """
        初始化分类器
        
        Args:
            api_key: LLM API密钥
        """
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise ValueError("需要设置LLM_API_KEY环境变量")
        
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        self.model = normalize_deepseek_model(os.getenv("LLM_MODEL", DEEPSEEK_V4_FLASH_MODEL))

        # 复用HTTP连接，避免每个batch都新建客户端带来的开销
        # 说明：本实例通常是全局单例（get_llm_classifier），进程生命周期内复用即可
        self._http_client = httpx.AsyncClient(timeout=240)
        
        # 系统提示词（用于缓存）
        self.system_prompt = self._build_system_prompt()
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词（收紧约束 + 边界说明）"""
        categories_list = "\n".join([
            f"{i+1}. {name}（{key}）: {self.CATEGORY_DESCRIPTIONS[key]}"
            for i, (key, name) in enumerate(self.CATEGORIES.items())
        ])
        boundary_notes = (
            "判定边界（不使用规则词表，仅基于语义判断）：\n"
            "- sports_medicine：涉及临床、损伤、康复、治疗、手术、诊断等医学情境优先归入。\n"
            "- sports_education：涉及学校课程、教学、教师、课堂、教育政策的研究优先归入。\n"
            "- training_science：涉及训练计划、周期化、专项训练、竞技表现提升的干预与评估优先归入。\n"
            "- exercise_science：涉及生理/生化/生物力学机制、人体与细胞/分子层面的机理研究优先归入。\n"
            "- fitness_monitoring：涉及体质监测、健康评估、可穿戴设备、监测指标分析优先归入。\n"
            "- sport_psychology：涉及动机、情绪、心理技能、心理测量优先归入。\n"
            "- sport_humanities：涉及政策、经济、社会学、文化、人群行为与管理优先归入。\n"
            "- sport_engineering：涉及装备/器材/场地、算法/仿真/数据系统、工程实现优先归入。\n"
        )

        return f"""你是一个运动科学文献分类专家。请根据文献的标题、完整摘要、PublicationType、MeSH术语，将其分类到以下8个类别中（可多选但最多2类）：

{categories_list}

{boundary_notes}

硬性要求：
1. 最多输出2个类别；若不确定时仅输出1个最符合的类别。
2. 仅输出上述8个类别的key，禁止使用未列出的key。
3. 对每个输出类别给出0~1的置信度；置信度<0.6的类别不要输出。
4. primary 必须是上述8个类别之一，且必须在输出的 categories 中；若只输出1类，则该类即为 primary。
5. 结合PublicationType与MeSH的语义辅助判断（不做机械匹配）。

输出格式（严格JSON）：
{{
  "categories": ["category_key1", "category_key2"],
  "confidence": [0.85, 0.65],
  "primary": "category_key1"
}}
"""
    
    async def classify_batch(
        self,
        articles: List[Dict[str, Any]],
        batch_size: int = 64,
        max_concurrent: int = 8  # 真正并发：同时处理8个批次（可用环境变量覆盖）
    ) -> List[Dict[str, Any]]:
        """
        批量分类文献（真正并发版本）
        
        Args:
            articles: 文献列表，每个包含title和abstract
            batch_size: 每批处理数量
            max_concurrent: 最大并发批次数量
        
        Returns:
            分类结果列表
        """
        total = len(articles)
        total_batches = (total + batch_size - 1) // batch_size
        
        # 允许通过环境变量调整并发，便于在全量回填/重建时降载以降低 503 概率
        try:
            max_concurrent = int(os.getenv("LLM_CLASSIFY_MAX_CONCURRENT", str(max_concurrent)))
        except Exception:
            max_concurrent = max_concurrent or 8

        print(f"   🤖 真正并发LLM分类: {total:,}篇 | {total_batches}批次 | {max_concurrent}并发")
        
        # 创建所有批次任务
        batches = []
        for i in range(0, len(articles), batch_size):
            batch = articles[i:i+batch_size]
            batch_num = i // batch_size + 1
            batches.append((batch_num, batch))
        
        # 并发处理批次
        semaphore = asyncio.Semaphore(max_concurrent)  # 控制并发数
        
        async def process_batch_with_limit(batch_num: int, batch: List[Dict[str, Any]]):
            """带并发限制的批次处理"""
            async with semaphore:
                try:
                    results = await self._classify_single_batch(batch)
                    print(f"   ✓ 批次 {batch_num}/{total_batches} 完成: {len(results)} 篇")
                    return batch_num, results
                except Exception as e:
                    print(f"   ❌ 批次 {batch_num}/{total_batches} 失败: {e}")
                    # 失败批次返回等长“空分类”，避免 merge_results(zip) 造成文章丢失
                    fallback = [{"categories": [], "confidence": [], "primary": None} for _ in batch]
                    return batch_num, fallback
        
        # 并发执行所有批次
        tasks = [
            process_batch_with_limit(batch_num, batch)
            for batch_num, batch in batches
        ]
        
        # 等待所有批次完成（真正并发）
        results_list = await asyncio.gather(*tasks)
        
        # 按批次顺序合并结果（保持顺序）
        results_list.sort(key=lambda x: x[0])  # 按batch_num排序
        results = []
        for batch_num, batch_results in results_list:
            results.extend(batch_results)
            
        completed = sum(len(r) for _, r in results_list)
        print(f"   ✅ LLM分类完成: {completed}/{total}篇")
        
        return results
    
    async def _classify_single_batch(
        self,
        batch: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        分类单个批次
        
        Args:
            batch: 文献批次
        
        Returns:
            分类结果
        """
        # 构建用户消息
        articles_text = []
        for idx, article in enumerate(batch):
            title = article.get('title', '') or ''
            abstract = article.get('abstract', '') or ''
            pub_types = article.get('pub_types') or article.get('publication_types') or []
            mesh_terms = article.get('mesh_terms') or []
            
            # 确保是字符串类型
            if not isinstance(title, str):
                title = str(title) if title else ''
            if not isinstance(abstract, str):
                abstract = str(abstract) if abstract else ''

            if not isinstance(pub_types, (list, tuple)):
                pub_types = [pub_types] if pub_types else []
            else:
                pub_types = list(pub_types)

            if not isinstance(mesh_terms, (list, tuple)):
                mesh_terms = [mesh_terms] if mesh_terms else []
            else:
                mesh_terms = list(mesh_terms)

            pub_types = [str(item) for item in pub_types if item]
            mesh_terms = [str(item) for item in mesh_terms if item]
            
            # 使用完整摘要（全量摘要）
            abstract_full = abstract if abstract else ""

            articles_text.append(f"""
文献{idx+1}:
标题: {title}
摘要: {abstract_full}
PublicationType: {', '.join(pub_types)}
MeSH术语: {', '.join(mesh_terms)}
""")
        
        user_message = f"""请分类以下{len(batch)}篇文献：

{''.join(articles_text)}

请返回JSON数组，每个元素对应一篇文献的分类结果。"""
        
        # 调用DeepSeek API
        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
        
        # 重试机制（可通过环境变量调整）
        try:
            max_retries = int(os.getenv("LLM_CLASSIFY_MAX_RETRIES", "2"))
        except Exception:
            max_retries = 2
        if max_retries < 0:
            max_retries = 2

        for retry in range(max_retries + 1):
            try:
                # 动态超时：第1次180秒，第2/3次240秒（针对大批量）
                timeout_seconds = 180 if retry == 0 else 240

                response = await self._http_client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.1,  # 低温度保证稳定性
                        "response_format": {"type": "json_object"},
                        "thinking": THINKING_DISABLED,
                    },
                    timeout=timeout_seconds,
                )
                    
                response.raise_for_status()
                data = response.json()
                
                # 解析结果
                content = data['choices'][0]['message']['content']
                parsed = json.loads(content)

                # 允许两种返回：
                # 1) 顶层对象：{"results": [...]}（与 response_format=json_object 更一致）
                # 2) 顶层数组：[...]
                if isinstance(parsed, dict) and 'results' in parsed:
                    results = parsed.get('results')
                elif isinstance(parsed, list):
                    results = parsed
                else:
                    results = [parsed]

                if not isinstance(results, list):
                    results = [results]

                # DeepSeek 有时会返回数量不匹配；必须对齐到 batch 大小，避免 zip 造成“丢文章”
                expected = len(batch)
                got = len(results)
                if got != expected:
                    print(f"⚠️  DeepSeek 返回数量异常: got {got}, expected {expected}，已自动对齐")
                    if got == 1:
                        results = results * expected
                    elif got < expected:
                        results = results + [
                            {"categories": [], "confidence": [], "primary": None}
                            for _ in range(expected - got)
                        ]
                    else:
                        results = results[:expected]

                return results
            
            except httpx.ReadTimeout as e:
                current_timeout = 180 if retry == 0 else 240
                if retry < max_retries:
                    next_timeout = 240
                    wait_time = (retry + 1) * 5  # 5秒, 10秒
                    print(f"⚠️  DeepSeek API超时（{current_timeout}秒），{wait_time}秒后重试 (下次{next_timeout}秒超时)...")
                    await asyncio.sleep(wait_time)
                    continue  # 重试
                else:
                    print(f"❌ DeepSeek API超时（180秒→240秒→240秒均失败）- 程序终止")
                    print(f"   提示: 可尝试降低batch_size (当前64 → 建议32)")
                    raise RuntimeError(f"DeepSeek API ReadTimeout after {max_retries} retries (180s→240s→240s)") from e
            
            except httpx.HTTPStatusError as e:
                status = getattr(e.response, "status_code", None)
                body = ""
                try:
                    body = (e.response.text or "")[:500]
                except Exception:
                    body = ""

                # 503/502/504/429 等通常为临时拥塞或限流，允许重试
                retryable = status in (429, 502, 503, 504, 529)
                if retryable and retry < max_retries:
                    wait_time = (retry + 1) * 8  # 8s, 16s
                    print(
                        f"⚠️  DeepSeek 暂时不可用(HTTP {status})，{wait_time}秒后重试 ({retry+1}/{max_retries})..."
                    )
                    await asyncio.sleep(wait_time)
                    continue

                print(f"❌ DeepSeek API调用失败 (HTTP {status}): {body}")
                print(f"   程序终止")
                raise RuntimeError(f"DeepSeek API HTTP {status}") from e
            
            except Exception as e:
                if retry < max_retries:
                    wait_time = (retry + 1) * 5
                    print(f"⚠️  DeepSeek API错误: {type(e).__name__}，{wait_time}秒后重试 ({retry+1}/{max_retries})...")
                    await asyncio.sleep(wait_time)
                    continue  # 重试
                else:
                    print(f"❌ DeepSeek API调用失败（已重试{max_retries}次）: {type(e).__name__}: {e}")
                    print(f"   程序终止")
                    import traceback
                    traceback.print_exc()
                    raise RuntimeError(f"DeepSeek API failed after {max_retries} retries: {type(e).__name__}") from e
    
    def _enforce_output_constraints(
        self,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """对单条LLM结果应用约束：合法类别、阈值、最多2类、primary一致性。"""
        allowed = set(self.CATEGORIES.keys())
        cats = result.get('categories', []) or []
        conf = result.get('confidence', []) or []
        primary = result.get('primary')

        # 过滤非法类别，并与置信度对齐
        pairs = [(c, float(conf[i]) if i < len(conf) else 0.0) for i, c in enumerate(cats) if c in allowed]
        # 置信度阈值
        pairs = [(c, s) for c, s in pairs if s >= 0.6]
        # 限制最多2类（按置信度降序）
        pairs.sort(key=lambda x: x[1], reverse=True)
        pairs = pairs[:2]

        if not pairs:
            # 如果全部被过滤，且primary是合法的，则仅保留primary（置信度设为0.6）
            if primary in allowed:
                cats = [primary]
                conf = [0.6]
            else:
                cats, conf = [], []
                primary = None
        else:
            cats = [p[0] for p in pairs]
            conf = [p[1] for p in pairs]
            # primary 校正：必须在 cats 且合法
            if primary not in cats:
                primary = cats[0]

        return {"categories": cats, "confidence": conf, "primary": primary}

    def merge_results(
        self,
        articles: List[Dict[str, Any]],
        classifications: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        合并文献和分类结果
        
        Args:
            articles: 原始文献列表
            classifications: 分类结果列表
        
        Returns:
            合并后的文献列表
        """
        merged = []
        for article, classification in zip(articles, classifications):
            constrained = self._enforce_output_constraints(classification or {})
            merged_article = article.copy()
            merged_article['subject_categories'] = constrained.get('categories', [])
            merged_article['classification_confidence'] = constrained.get('confidence', [])
            merged_article['primary_category'] = constrained.get('primary')
            merged.append(merged_article)
        
        return merged


# 全局实例
_classifier = None

def get_llm_classifier() -> LLMClassifier:
    """获取LLM分类器实例"""
    global _classifier
    if _classifier is None:
        _classifier = LLMClassifier()
    return _classifier
