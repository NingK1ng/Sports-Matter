"""
WiW生成服务

负责召回相似文献、生成WiW卡片、顶刊推荐等核心逻辑
"""

import asyncio
import hashlib
import json
import re
import time
from typing import List, Dict, Any, Optional, Tuple
import httpx

from core.external.pubmed import get_pubmed_client
from core.cache import cache_get, cache_set
from core.config import settings
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model
from modules.research_gap.prompts.wiw_template import get_wiw_prompt, get_wiw_system_prompt


class WiWGenerator:
    """WiW生成器"""
    
    def __init__(self):
        self.pubmed_client = get_pubmed_client()
        self.deepseek_api_key = settings.deepseek_api_key
        self.deepseek_base_url = settings.deepseek_base_url or "https://api.deepseek.com"
    
    async def generate_wiw(
        self,
        pmid: str,
        top_k: int = 10,
        language: str = "zh",
        enable_inspiration: bool = True,
        model: str = None
    ) -> Dict[str, Any]:
        """
        生成WiW分析卡片
        
        Args:
            pmid: 输入文献PMID
            top_k: 召回文献数量（5/10/15）
            language: 输出语言（zh/en）
            enable_inspiration: 是否启用顶刊推荐
        
        Returns:
            Dict包含：
            - card: {focus, next_questions, conflicts, gaps}
            - references: [{pmid, title, doi, abstract}, ...]
            - top_journal_recommendations: [{title, journal, doi, pmid}, ...]
            - meta: {recall_mode, strategy_version, model_version, dedup_count, elapsed_ms, degradation}
        """
        start_time = time.time()
        meta = {
            "recall_mode": "elink",
            "strategy_version": "v1",
            "model_version": DEEPSEEK_V4_FLASH_MODEL,
            "template_version": "v1",
            "dedup_count": 0,
            "elapsed_ms": 0,
            "degradation": None
        }
        
        # 1. 获取输入文献详情
        print(f"📖 获取输入文献详情: PMID {pmid}")
        input_article = await self._fetch_article_details(pmid)
        if not input_article:
            raise ValueError(f"PMID_NOT_FOUND: 无法获取PMID {pmid}的详情")
        
        # 2. 召回相似文献（使用ELink，带自适应retmax策略）
        print(f"🔍 召回相似文献（ELink）")
        related_pmids = None
        
        # 尝试不同的retmax值，从小到大
        # 某些PMID在retmax=50时返回0，但retmax=100时返回大量结果
        retmax_values = [50, 100, 200]
        
        for retmax in retmax_values:
            cache_key_recall = self._generate_cache_key(pmid, "elink", retmax)
            cached_result = await cache_get(cache_key_recall)
            
            # 如果缓存的是空结果，忽略缓存
            if cached_result is not None and len(cached_result) > 0:
                print(f"✅ 缓存命中 (retmax={retmax}): {len(cached_result)}篇")
                related_pmids = cached_result
                break
            
            # 调用ELink API
            try:
                print(f"🔍 尝试ELink (retmax={retmax})...")
                result = await self.pubmed_client.elink(pmid, retmax=retmax)
                print(f"   返回: {len(result) if result else 0}篇")
                
                if result and len(result) > 0:
                    related_pmids = result
                    # 缓存成功的结果
                    await cache_set(cache_key_recall, related_pmids, ttl=172800)
                    print(f"✅ ELink成功 (retmax={retmax}): {len(related_pmids)}篇")
                    break
                    
            except Exception as e:
                print(f"⚠️  ELink (retmax={retmax}) 失败: {e}")
                # 继续尝试下一个retmax
                continue
        
        # 如果所有retmax都失败了
        if not related_pmids or len(related_pmids) == 0:
            print(f"❌ 所有ELink尝试均返回0篇 (PMID: {pmid}, 尝试过retmax={retmax_values})")
            print(f"💡 可能原因: 1) 文献太新未建立链接 2) 文献类型特殊 3) PubMed数据库问题")
            related_pmids = []
        
        if len(related_pmids) < 5:
            raise ValueError(f"LOW_RECALL: 相似文献不足（仅{len(related_pmids)}篇，需至少5篇）")
        
        # 3. PMID去重（移除输入PMID）
        seen_pmids = {pmid}
        unique_pmids = [p for p in related_pmids if p not in seen_pmids and not seen_pmids.add(p)]
        meta["dedup_count"] = len(related_pmids) - len(unique_pmids)
        
        # 4. 截取topK
        selected_pmids = unique_pmids[:top_k]
        print(f"📚 选择Top{top_k}文献（去重后{len(unique_pmids)}篇 → {len(selected_pmids)}篇）")
        
        # 5. 获取文献详情（批量）
        print(f"📥 批量获取{len(selected_pmids)}篇文献详情（标题+摘要）")
        references = await self._fetch_articles_batch(selected_pmids)
        
        # 6. 顶刊推荐（强制推荐2-8篇）
        print(f"⭐ 获取顶刊推荐（模块2全文检索，强制2-8篇）")
        # 构建排除集合：只排除输入PMID（不排除ELink召回的文献，允许重叠）
        exclude_set = {pmid}  # 只排除输入PMID
        top_journal_recommendations = await self._fetch_top_journal_recommendations(
            input_article["title"],
            input_article["abstract"],
            exclude_set,  # 只传入输入PMID
            input_title_for_dedup=input_article["title"]  # 传入输入标题用于标题去重
        )
        
        # 7. 检查上下文是否超限（简化版，不做降级）
        total_tokens = self._estimate_tokens(input_article, references)
        print(f"📊 估计Token数: {total_tokens}")
        
        if total_tokens > 30000:  # DeepSeek-Reasoner上限32K，留2K余量
            print(f"⚠️  Token数超限（{total_tokens} > 30000），但根据要求不降级，继续生成")
            meta["degradation"] = {
                "triggered": True,
                "reason": "context_overflow",
                "original_topK": top_k,
                "final_topK": top_k,
                "dropped_count": 0,
                "strategy": "no_degradation_per_requirement"
            }
        
        # 8. 生成WiW（调用DeepSeek）
        print(f"🤖 调用DeepSeek生成WiW")
        cache_key_gen = self._generate_generation_cache_key(
            pmid, top_k, selected_pmids, "v1", DEEPSEEK_V4_FLASH_MODEL
        )
        
        card_content = await cache_get(cache_key_gen)
        if card_content is None:
            card_content = await self._call_deepseek(
                input_article["title"],
                input_article["abstract"],
                references,
                language,
                model
            )
            await cache_set(cache_key_gen, card_content, ttl=604800)  # 7天
        else:
            print(f"✅ 生成缓存命中")
        
        # 9. 组装返回结果
        meta["elapsed_ms"] = int((time.time() - start_time) * 1000)
        
        return {
            "card": card_content,
            "references": [
                {
                    "pmid": ref["pmid"],
                    "title": ref["title"],
                    "doi": ref.get("doi", ""),
                    "abstract": ref.get("abstract", "")
                }
                for ref in references
            ],
            "top_journal_recommendations": top_journal_recommendations,
            "meta": meta
        }
    
    async def _fetch_article_details(self, pmid: str) -> Optional[Dict[str, str]]:
        """获取单篇文献详情（标题+摘要），带重试机制"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                summaries = await self.pubmed_client.fetch_summary([pmid])
                if not summaries:
                    if attempt < max_retries - 1:
                        print(f"⚠️  Summary返回空 (PMID: {pmid}), 重试 {attempt + 1}/{max_retries}...")
                        await asyncio.sleep(2)
                        continue
                    else:
                        print(f"❌ Summary重试{max_retries}次后仍返回空 (PMID: {pmid})")
                        return None
                
                article = summaries[0]
                abstract = await self.pubmed_client.fetch_abstract(pmid)
                
                return {
                    "pmid": pmid,
                    "title": article.get("title", ""),
                    "abstract": abstract or "",
                    "doi": article.get("doi", "")
                }
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠️  获取文献详情失败 (PMID: {pmid}), 重试 {attempt + 1}/{max_retries}: {e}")
                    await asyncio.sleep(2)
                else:
                    print(f"❌ 获取文献详情重试{max_retries}次后仍失败 (PMID: {pmid}): {e}")
                    return None
        
        return None
    
    async def _fetch_articles_batch(self, pmids: List[str]) -> List[Dict[str, str]]:
        """批量获取文献详情"""
        # 先获取summaries
        summaries = await self.pubmed_client.fetch_summary(pmids)
        summary_map = {s["pmid"]: s for s in summaries}
        
        # 并发获取摘要
        tasks = [self.pubmed_client.fetch_abstract(p) for p in pmids]
        abstracts = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for idx, pmid in enumerate(pmids):
            if pmid in summary_map:
                abstract = abstracts[idx] if not isinstance(abstracts[idx], Exception) else ""
                results.append({
                    "pmid": pmid,
                    "title": summary_map[pmid].get("title", ""),
                    "abstract": abstract or "",
                    "doi": summary_map[pmid].get("doi", "")
                })
        
        return results
    
    async def _fetch_top_journal_recommendations(
        self,
        input_title: str,
        input_abstract: str,
        exclude_pmids: set,
        input_title_for_dedup: str = None
    ) -> List[Dict[str, str]]:
        """
        从模块2获取顶刊推荐（13本期刊全文检索）
        
        Args:
            input_title: 输入文献标题
            input_abstract: 输入文献摘要
            exclude_pmids: 已召回的PMID集合（需要去重）
        
        Returns:
            List of {title, journal, doi, pmid}
        """
        try:
            from core.database import get_db_session
            from modules.journals.services.search_service import SearchService
            
            # 提取关键词（使用LLM，更智能）
            keywords_str = await self._extract_keywords_with_llm(input_title)
            all_keywords = keywords_str.split()
            if not all_keywords:
                print(f"⚠️  无法从标题提取关键词")
                return []
            
            print(f"🔍 提取的关键词: {all_keywords} ({len(all_keywords)}个)")
            
            # 获取数据库会话
            async with get_db_session() as session:
                search_service = SearchService(session)
                
                # 递减策略：从多到少尝试关键词，直到找到可用结果（过滤后>0）
                articles = []
                total = 0
                filtered_articles_final = []
                
                # 尝试不同数量的关键词：min(5, len) → 4 → 3 → 2 → 1
                max_keywords = min(5, len(all_keywords))
                for num_keywords in range(max_keywords, 0, -1):  # 改为从max到1
                    keywords = " ".join(all_keywords[:num_keywords])
                    print(f"🔍 尝试{num_keywords}个关键词: '{keywords}'")
                    
                    # 在模块2全部数据中全文检索（K_raw=50）
                    articles, total = await search_service.search_articles(
                        keywords=keywords,
                        search_scope="tiab",  # 标题+摘要
                        sort_by="relevance",
                        page=1,
                        per_page=50
                    )
                    
                    print(f"   检索结果: {len(articles)}篇")
                    
                    if len(articles) == 0:
                        continue  # 继续递减
                    
                    # 立即过滤，检查是否有可用文章
                    temp_filtered = []
                    excluded_patterns = [
                        r'\bnews\b', r'\beditorial\b', r'\bletter\b', r'\bcorrection\b',
                        r'\bretraction\b', r'\bcomment\b', r'\bnote\b'
                    ]
                    
                    for article in articles:
                        title_lower = article.title.lower()
                        is_excluded = any(re.search(pattern, title_lower) for pattern in excluded_patterns)
                        pmid_excluded = article.pmid and article.pmid in exclude_pmids
                        
                        title_excluded = False
                        if input_title_for_dedup:
                            input_title_clean = input_title_for_dedup.lower().strip()
                            article_title_clean = article.title.lower().strip()
                            title_excluded = (article_title_clean == input_title_clean)
                        
                        if not is_excluded and not pmid_excluded and not title_excluded:
                            temp_filtered.append(article)
                    
                    print(f"   过滤后: {len(temp_filtered)}篇")
                    
                    if len(temp_filtered) > 0:
                        print(f"✅ 找到可用结果，停止递减")
                        filtered_articles_final = temp_filtered
                        break  # 找到可用结果，停止
                    else:
                        print(f"   过滤后无可用文章，继续递减关键词...")
                
                print(f"📚 顶刊推荐最终过滤后剩余{len(filtered_articles_final)}篇")
                
                # 使用已经过滤好的结果
                filtered_articles = filtered_articles_final
                
                # 强制返回2-8篇
                if len(filtered_articles) == 0:
                    print(f"⚠️  过滤后无可用文章，尝试放宽条件（保留前50篇中的前8篇，仅去除输入文献）")
                    # 放宽条件：只去除输入文献本身，保留其他所有文章
                    relaxed_articles = []
                    for article in articles[:50]:  # 从原始结果中取前50篇
                        title_excluded = False
                        if input_title_for_dedup:
                            input_title_clean = input_title_for_dedup.lower().strip()
                            article_title_clean = article.title.lower().strip()
                            # 只检查标题完全匹配
                            title_excluded = (article_title_clean == input_title_clean)
                        
                        pmid_excluded = article.pmid and article.pmid in exclude_pmids
                        
                        if not title_excluded and not pmid_excluded:
                            relaxed_articles.append(article)
                    
                    filtered_articles = relaxed_articles
                    print(f"✅ 放宽条件后剩余{len(filtered_articles)}篇")
                
                # 确保至少2篇，最多8篇
                if len(filtered_articles) < 2:
                    print(f"⚠️  过滤后仅有{len(filtered_articles)}篇，少于最低要求2篇")
                    # 如果少于2篇，尝试放宽条件补足
                    if len(filtered_articles) < 2:
                        print(f"❌ 无法满足最低2篇顶刊推荐要求（当前仅{len(filtered_articles)}篇）")
                        return []
                
                # 取2-8篇（尽量同时包含运动科学顶刊与CNS顶刊）
                top_articles = filtered_articles[:8]
                try:
                    has_cns = any(getattr(a, "category", None) == "cns" for a in top_articles)
                    has_sports = any(getattr(a, "category", None) == "sports_science" for a in top_articles)

                    if not has_cns:
                        cns_candidate = next((a for a in filtered_articles if getattr(a, "category", None) == "cns"), None)
                        if cns_candidate:
                            for replace_idx in range(len(top_articles) - 1, -1, -1):
                                if getattr(top_articles[replace_idx], "category", None) != "cns":
                                    top_articles[replace_idx] = cns_candidate
                                    break

                    if not has_sports:
                        sports_candidate = next(
                            (a for a in filtered_articles if getattr(a, "category", None) == "sports_science"),
                            None
                        )
                        if sports_candidate:
                            for replace_idx in range(len(top_articles) - 1, -1, -1):
                                if getattr(top_articles[replace_idx], "category", None) != "sports_science":
                                    top_articles[replace_idx] = sports_candidate
                                    break
                except Exception:
                    pass
                
                # 格式化返回
                recommendations = []
                for article in top_articles:
                    recommendations.append({
                        "title": article.title,
                        "journal": article.journal_name or "Unknown",
                        "doi": article.doi or "",
                        "pmid": article.pmid or ""
                    })
                
                print(f"⭐ 返回{len(recommendations)}篇顶刊推荐（强制1-3篇）")
                return recommendations
            
            return []
            
        except Exception as e:
            print(f"❌ 顶刊推荐失败: {e}")
            import traceback
            traceback.print_exc()
            raise  # 抛出异常，不使用fallback
    
    async def _extract_keywords_with_llm(self, title: str) -> str:
        """使用LLM提取关键词（更智能）"""
        try:
            import httpx
            from core.config import settings
            
            prompt = f"""从以下学术文献标题中提取3-5个最核心的关键词或短语，用于检索相关文献。

标题：{title}

要求：
1. 优先提取：核心概念、研究对象、方法名、技术术语、领域专有名词
2. 保留复合词作为整体（如"machine learning"、"climate change"）
3. 保留专业术语的完整性（如缩写HR+/HER2-应保留为整体）
4. 只返回关键词，用空格分隔，不要解释

关键词："""
            
            print(f"🤖 LLM提取关键词...")
            
            # 直接调用DeepSeek API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": DEEPSEEK_V4_FLASH_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 50,
                        "temperature": 0.3,
                        "thinking": THINKING_DISABLED,
                    },
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
            
            keywords = data["choices"][0]["message"]["content"].strip()
            
            # Token统计
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            cost = (input_tokens * 0.001 + output_tokens * 0.002) / 1000  # RMB
            
            print(f"   LLM关键词: '{keywords}'")
            print(f"   Token: {input_tokens}+{output_tokens}, 成本: ¥{cost:.6f}")
            
            return keywords
            
        except Exception as e:
            print(f"⚠️  LLM关键词提取失败，使用规则fallback: {e}")
            return self._extract_keywords_fallback(title)
    
    def _extract_keywords_fallback(self, title: str) -> str:
        """规则提取关键词（fallback）"""
        # 移除常见停用词
        stopwords = {"and", "or", "the", "a", "an", "of", "in", "on", "at", "to", "for", 
                    "with", "by", "from", "as",
                    "与", "和", "的", "在", "对", "关于", "研究", "分析"}
        words = title.lower().split()
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return " ".join(keywords[:5])  # 取前5个关键词
    
    def _estimate_tokens(self, input_article: Dict, references: List[Dict]) -> int:
        """估算Token数（1 token ≈ 4字符）"""
        total_chars = len(input_article["title"]) + len(input_article.get("abstract", ""))
        for ref in references:
            total_chars += len(ref["title"]) + len(ref.get("abstract", ""))
        
        # 加上prompt模板的字符数（约2000字符）
        total_chars += 2000
        
        return total_chars // 4
    
    async def _call_deepseek(
        self,
        input_title: str,
        input_abstract: str,
        references: List[Dict],
        language: str,
        model: str = None
    ) -> Dict[str, Any]:
        """调用DeepSeek API生成WiW"""
        prompt = get_wiw_prompt(input_title, input_abstract, references, language)
        system_prompt = get_wiw_system_prompt(language)
        
        # 优先使用传入的模型，否则从环境变量读取，最后使用默认值
        import os
        model_name = normalize_deepseek_model(model or os.getenv("LLM_MODEL") or DEEPSEEK_V4_FLASH_MODEL)
        
        import time
        start_time = time.time()
        print(f"\n{'='*60}")
        print(f"🤖 调用DeepSeek模型: {model_name}")
        print(f"⏱️  开始时间: {time.strftime('%H:%M:%S')}")
        print(f"{'='*60}")
        
        timeout_seconds = 90.0
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                response = await client.post(
                    f"{self.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.7,
                        "response_format": {"type": "json_object"},  # 启用JSON mode
                        "max_tokens": 4000,  # 防止JSON被截断
                        "thinking": THINKING_DISABLED,
                    }
                )
                
                response.raise_for_status()
                result = response.json()
                
                # 记录详细的API响应信息
                elapsed_time = time.time() - start_time
                print(f"\n✅ DeepSeek响应成功 (耗时: {elapsed_time:.1f}s)")
                
                # Token使用统计
                usage = result.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                prompt_cache_hit_tokens = usage.get("prompt_cache_hit_tokens", 0)
                prompt_cache_miss_tokens = usage.get("prompt_cache_miss_tokens", 0)
                
                print(f"\n📊 Token统计:")
                print(f"   输入Token: {prompt_tokens:,}")
                if prompt_cache_hit_tokens > 0:
                    print(f"   - 缓存命中: {prompt_cache_hit_tokens:,} (省钱💰)")
                if prompt_cache_miss_tokens > 0:
                    print(f"   - 缓存未命中: {prompt_cache_miss_tokens:,}")
                print(f"   输出Token: {completion_tokens:,}")
                print(f"   总Token: {total_tokens:,}")
                
                # 成本估算（DeepSeek定价）
                # 输入：缓存命中0.2元/M，缓存未命中2元/M
                # 输出：3元/M
                input_cost = (prompt_cache_hit_tokens * 0.2 + prompt_cache_miss_tokens * 2.0) / 1_000_000
                output_cost = completion_tokens * 3.0 / 1_000_000
                total_cost = input_cost + output_cost
                print(f"\n💰 预估成本:")
                print(f"   输入: ¥{input_cost:.4f}")
                print(f"   输出: ¥{output_cost:.4f}")
                print(f"   总计: ¥{total_cost:.4f}")
                
                # 解析响应
                message = result["choices"][0]["message"]
                content = message["content"]
                
                # 如果返回推理过程，打印前缀用于排查
                if "reasoning_content" in message:
                    reasoning = message["reasoning_content"]
                    print(f"\n🧠 推理过程 (前500字符):")
                    print(f"   {reasoning[:500]}...")
                    print(f"   推理长度: {len(reasoning)} 字符")
                
                # 检查空content（DeepSeek JSON mode可能返回空）
                if not content or not content.strip():
                    print(f"⚠️  DeepSeek返回空content，重试中...")
                    raise ValueError("LLM_GENERATION_FAILED: DeepSeek返回空content")
                
                # 去除可能的markdown标记
                content = content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                # 解析JSON
                print(f"\n📝 生成内容 (前300字符):")
                print(f"   {content[:300]}...")
                print(f"   总长度: {len(content)} 字符")
                
                card = json.loads(content)
                
                # 验证字段完整性
                required_fields = ["focus", "next_questions", "conflicts", "gaps"]
                for field in required_fields:
                    if field not in card or not card[field]:
                        # next_questions和gaps都是数组格式
                        card[field] = [] if field in ["next_questions", "gaps"] else ""
                
                print(f"\n✅ JSON解析成功")
                print(f"   核心聚焦: {len(card['focus'])} 字符")
                print(f"   下一步问题: {len(card['next_questions'])} 个")
                print(f"   研究争议: {len(card['conflicts'])} 字符")
                print(f"   研究空白: {len(card['gaps'])} 个")
                print(f"{'='*60}\n")
                
                return card
                
            except json.JSONDecodeError as e:
                print(f"⚠️  DeepSeek返回非法JSON: {e}")
                raise ValueError("LLM_GENERATION_FAILED: DeepSeek返回非法JSON")
            except httpx.TimeoutException:
                print(f"⚠️  DeepSeek调用超时（>{timeout_seconds}s）")
                print(f"💡 提示：可减少召回文献数量(top_k)后重试")
                raise ValueError(f"LLM_TIMEOUT: DeepSeek调用超时（>{timeout_seconds}s）")
            except Exception as e:
                print(f"⚠️  DeepSeek调用失败: {e}")
                raise ValueError(f"LLM_GENERATION_FAILED: {str(e)}")
    
    def _generate_cache_key(self, pmid: str, mode: str, retmax: int) -> str:
        """生成召回缓存键"""
        return f"wiw:recall:{mode}:{pmid}:{retmax}"
    
    def _generate_generation_cache_key(
        self,
        pmid: str,
        top_k: int,
        reference_pmids: List[str],
        template_version: str,
        model_version: str
    ) -> str:
        """生成WiW生成缓存键"""
        refs_str = ",".join(sorted(reference_pmids))
        refs_hash = hashlib.md5(refs_str.encode()).hexdigest()[:8]
        return f"wiw:gen:{pmid}:{top_k}:{refs_hash}:{template_version}:{model_version}"
