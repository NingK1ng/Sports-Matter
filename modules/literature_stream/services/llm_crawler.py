"""
新架构PubMed爬虫：大闸门 + LLM分类
替代原有的基于8个学科检索式的爬虫
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
import pytz
import os
import json
import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dateutil import parser as date_parser
from dotenv import load_dotenv

from core.external.pubmed import get_pubmed_client
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model
from modules.literature_stream.models.literature import Literature, CrawlTaskLog
from modules.literature_stream.services.animal_classifier import get_animal_classifier
from modules.literature_stream.services.llm_classifier import get_llm_classifier
from modules.literature_stream.services.journal_matcher import JournalMatcher

# 加载环境变量
load_dotenv()


# 通用运动科学闸门
SPORTS_GATE = """(
  "Sports"[mh] OR
  "Athletes"[mh] OR
  "Sports Medicine"[mh] OR
  "Athletic Performance"[mh] OR
  "Athletic Injuries"[mh] OR
  "Physical Education and Training"[mh] OR
  "Exercise"[mh] OR
  "Motor Activity"[mh] OR
  "Physical Fitness"[mh] OR
  "Exercise Therapy"[mh] OR
  sport*[tiab] OR
  athlet*[tiab] OR
  exercis*[tiab] OR
  "physical activity"[tiab] OR
  "physical fitness"[tiab] OR
  "strength training"[tiab] OR
  "resistance training"[tiab] OR
  rehabilitation[tiab] OR
  biomechanic*[tiab] OR
  physiotherap*[tiab] OR
  kinesiology[tiab] OR
  strength[tiab] OR
  endurance[tiab] OR
  gait[tiab]
)"""


class LLMPubMedCrawler:
    """基于LLM分类的PubMed爬虫"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.pubmed = get_pubmed_client()
        self.llm_classifier = get_llm_classifier()
        self.journal_matcher = JournalMatcher(db_session)
        self.utc = pytz.UTC
        self.utc8 = pytz.timezone('Asia/Shanghai')

        # DeepSeek API配置（用于相关性过滤）
        self.api_key = os.getenv("LLM_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        self.model = normalize_deepseek_model(os.getenv("LLM_MODEL", DEEPSEEK_V4_FLASH_MODEL))

    async def _judge_relevance(
        self,
        session: aiohttp.ClientSession,
        title: str,
        abstract: str
    ) -> Tuple[float, str]:
        """
        判断文献与运动科学的相关度（宽松打分）

        Returns:
            (relevance_score, reason)
        """
        prompt = f"""你是运动科学专家。根据标题和摘要判断该论文与以下内容的相关度：
- 运动科学 / 体育科学（sports science）
- 体育工程 / 体育技术（sports engineering）
- 运动医学 / 康复（sports medicine, rehabilitation）
- 运动训练 / 身体活动 / 体力活动（exercise training, physical activity）
- 体育教育 / 体育人文（physical education, sport humanities）
- 以及其他与运动科学相关的全部方向

评分标准（适当宽松，分数精确到小数点后两位）：
- 1.00: 核心运动科学研究（主题完全聚焦运动/体育/锻炼）
- 0.70-0.90: 高度相关
- 0.40-0.60: 中度相关
- 0.20-0.30: 弱相关
- 0.00-0.10: 不相关（与运动科学或体育完全无关）

注意：
1. 只要论文**实质性涉及**运动/体育/锻炼/身体活动/运动员，即使不是核心主题，也应给予≥0.4的分数
2. 如果论文在运动/体育数据上测试算法或模型，应视为相关（≥0.5）
3. 只有完全无关的论文才给<0.2的分数

标题: {title}

摘要: {abstract[:500] if abstract else '无摘要'}

请以JSON格式输出：
{{
  "relevance": 0.85,
  "reason": "判断理由（50字以内）"
}}
"""

        messages = [{"role": "user", "content": prompt}]

        max_retries = 2
        for retry in range(max_retries + 1):
            try:
                response = await session.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                        "thinking": THINKING_DISABLED,
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                )

                response.raise_for_status()
                data = await response.json()
                content = data['choices'][0]['message']['content']
                result = json.loads(content)

                relevance = float(result.get('relevance', 0.0))
                reason = result.get('reason', '')

                return relevance, reason

            except Exception as e:
                if retry < max_retries:
                    await asyncio.sleep((retry + 1) * 2)
                    continue
                else:
                    # 保守策略：连续调用失败时视为“暂保留”，避免误删相关文章
                    return 0.5, f"API错误: {type(e).__name__}，默认保留"

    async def _filter_by_relevance(
        self,
        articles: List[Dict[str, Any]],
        threshold: float = 0.25,
        max_concurrent: int = 64
    ) -> List[Dict[str, Any]]:
        """
        相关性过滤（64并发）

        Returns:
            相关文章列表（relevance >= threshold）
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        filtered = []

        async def process_one(article: Dict[str, Any], idx: int, session: aiohttp.ClientSession):
            async with semaphore:
                relevance, reason = await self._judge_relevance(
                    session,
                    article['title'],
                    article.get('abstract', '') or ''
                )

                if relevance >= threshold:
                    article['sport_relevance'] = relevance
                    article['relevance_reason'] = reason
                    filtered.append(article)
                    return idx, 'keep', relevance
                else:
                    return idx, 'filter', relevance

        total = len(articles)
        async with aiohttp.ClientSession() as session:
            tasks = [process_one(article, i, session) for i, article in enumerate(articles)]
            results = await asyncio.gather(*tasks)

        kept = sum(1 for _, status, _ in results if status == 'keep')
        filtered_out = sum(1 for _, status, _ in results if status == 'filter')

        print(f"   ✅ 相关性过滤: {kept:,}/{total:,}篇通过 (阈值≥{threshold})")
        print(f"   🗑️  过滤掉: {filtered_out:,}篇\n")

        return filtered

    def _classify_literature_type(
        self,
        pub_types: list[str],
        mesh_terms: list[str]
    ) -> list[str]:
        """
        规则分类文献类型（纯规则，零成本）

        Args:
            pub_types: PublicationType列表
            mesh_terms: MeSH术语列表

        Returns:
            文献类型列表（单元素数组）
        """
        # 1. Meta分析 & 系统综述（最高优先级）
        if any(t in pub_types for t in ['Meta-Analysis', 'Systematic Review']):
            return ['meta_analysis']

        # 2. 综述（排除Meta和系统综述）
        if 'Review' in pub_types and not any(t in pub_types for t in ['Systematic Review', 'Meta-Analysis']):
            return ['review']

        # 3. 指南/共识/Protocol
        if any(t in pub_types for t in ['Practice Guideline', 'Guideline', 'Consensus Development Conference']):
            return ['guideline']

        # 4. 原创研究二分类（基于MeSH）
        has_animals = 'Animals' in mesh_terms
        has_humans = 'Humans' in mesh_terms

        if has_animals and not has_humans:
            return ['original_animal']
        else:
            return ['original_human']
    
    async def incremental_crawl(
        self,
        start_utc: Optional[datetime] = None,
        end_utc: Optional[datetime] = None,
        task_type: str = 'incremental_daily',
        date_field: str = "DP",
    ) -> Dict[str, Any]:
        """
        增量爬取（每日定时任务）

        Args:
            start_utc: 开始时间（UTC），默认为今天-3天
            end_utc: 结束时间（UTC），默认为现在
            task_type: 任务类型标识
            date_field: PubMed日期字段（DP 或 EDAT）；默认DP以保持回填语义

        Returns:
            爬取结果统计
        """
        # 默认时间窗口：3天（与模块2保持一致）
        if not end_utc:
            end_utc = datetime.now(self.utc)
        if not start_utc:
            start_utc = end_utc - timedelta(days=3)

        # 构建日期过滤
        date_field_norm = (date_field or "DP").strip().upper()
        if date_field_norm == "EDAT":
            edat_start = start_utc.astimezone(self.utc).strftime("%Y/%m/%d %H:%M:%S")
            edat_end = end_utc.astimezone(self.utc).strftime("%Y/%m/%d %H:%M:%S")
            date_filter = f'("{edat_start}"[EDAT] : "{edat_end}"[EDAT])'
        elif date_field_norm == "DP":
            pdat_start = start_utc.strftime("%Y/%m/%d")
            pdat_end = end_utc.strftime("%Y/%m/%d")
            date_filter = f'("{pdat_start}"[dp] : "{pdat_end}"[dp])'
        else:
            raise ValueError(f"Unsupported date_field={date_field!r}; expected 'DP' or 'EDAT'")

        # 记录任务
        task_log = CrawlTaskLog(
            task_type=task_type,
            category_key='all_sports',
            query_params={
                'start_utc': start_utc.isoformat(),
                'end_utc': end_utc.isoformat(),
                'date_filter': date_filter,
                'date_field': date_field_norm,
                'sports_gate': SPORTS_GATE,
                'window_days': 3,
            },
            status='running',
            started_at=datetime.utcnow(),
        )
        self.db.add(task_log)
        await self.db.commit()

        try:
            print(f"\n{'='*80}")
            print(f"🔄 增量爬取（3天窗口）")
            print(f"{'='*80}")
            print(f"时间范围: {start_utc.strftime('%Y-%m-%d')} 至 {end_utc.strftime('%Y-%m-%d')}")
            print(f"{'='*80}\n")

            # 执行爬取和分类
            results = await self._fetch_classify_store(
                date_filter=date_filter,
                task_log=task_log,
                start_utc=start_utc,
                end_utc=end_utc,
                date_field=date_field_norm,
            )

            # 更新任务状态
            task_log.status = 'success'
            task_log.total_fetched = results['total_processed']
            task_log.new_inserted = results['new_count']
            task_log.duplicates_skipped = results['duplicates_skipped']
            task_log.finished_at = datetime.utcnow()
            task_log.duration_seconds = int(
                (task_log.finished_at - task_log.started_at).total_seconds()
            )
            await self.db.commit()

            return results

        except Exception as e:
            task_log.status = 'failed'
            task_log.error_message = str(e)
            task_log.finished_at = datetime.utcnow()
            await self.db.commit()
            raise

    async def warm_start_crawl(
        self,
        start_date: str,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        回填爬取（从指定日期到现在）

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD），默认为今天

        Returns:
            爬取结果统计
        """
        # 解析日期
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=self.utc8)
        start_utc = start_dt.astimezone(self.utc)
        
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=self.utc8)
            end_utc = end_dt.astimezone(self.utc)
        else:
            end_utc = datetime.now(self.utc)
        
        # 构建日期过滤
        pdat_start = start_utc.strftime('%Y/%m/%d')
        pdat_end = end_utc.strftime('%Y/%m/%d')
        date_filter = f'("{pdat_start}"[dp] : "{pdat_end}"[dp])'
        
        # 记录任务
        task_log = CrawlTaskLog(
            task_type='warm_start_llm',
            category_key='all_sports',  # 不再按学科分类
            query_params={
                'start_date': start_date,
                'end_date': end_date or datetime.now().strftime('%Y-%m-%d'),
                'start_utc': start_utc.isoformat(),
                'end_utc': end_utc.isoformat(),
                'date_filter': date_filter,
                'sports_gate': SPORTS_GATE
            },
            status='running',
            started_at=datetime.utcnow(),
        )
        self.db.add(task_log)
        await self.db.commit()
        
        try:
            print(f"\n{'='*80}")
            print(f"🚀 大闸门+LLM分类爬虫")
            print(f"{'='*80}")
            print(f"时间范围: {start_date} 至 {end_date or '今天'}")
            print(f"{'='*80}\n")
            
            # 执行爬取和分类
            results = await self._fetch_classify_store(
                date_filter=date_filter,
                task_log=task_log,
                start_utc=start_utc,
                end_utc=end_utc,
                date_field="DP",
            )
            
            # 更新任务状态
            task_log.status = 'success'
            task_log.total_fetched = results['total_processed']
            task_log.new_inserted = results['new_count']
            task_log.duplicates_skipped = results['duplicates_skipped']
            task_log.finished_at = datetime.utcnow()
            task_log.duration_seconds = int(
                (task_log.finished_at - task_log.started_at).total_seconds()
            )
            await self.db.commit()
            
            return results
            
        except Exception as e:
            task_log.status = 'failed'
            task_log.error_message = str(e)
            task_log.finished_at = datetime.utcnow()
            await self.db.commit()
            raise
    
    async def _fetch_classify_store(
        self,
        date_filter: str,
        task_log: CrawlTaskLog,
        start_utc: Optional[datetime] = None,
        end_utc: Optional[datetime] = None,
        date_field: str = "DP",
    ) -> Dict[str, Any]:
        """
        获取、分类、存储文献
        
        Args:
            date_filter: PubMed日期过滤式
            task_log: 任务日志
            
        Returns:
            处理结果统计
        """
        # 1. 构建查询
        date_field_norm = (date_field or "DP").strip().upper()
        query = f"{SPORTS_GATE} AND {date_filter}"

        def _build_date_filter(sub_start: datetime, sub_end: datetime) -> str:
            if date_field_norm == "EDAT":
                edat_start = sub_start.astimezone(self.utc).strftime("%Y/%m/%d %H:%M:%S")
                edat_end = sub_end.astimezone(self.utc).strftime("%Y/%m/%d %H:%M:%S")
                return f'("{edat_start}"[EDAT] : "{edat_end}"[EDAT])'
            if date_field_norm == "DP":
                pdat_start = sub_start.strftime("%Y/%m/%d")
                pdat_end = sub_end.strftime("%Y/%m/%d")
                return f'("{pdat_start}"[dp] : "{pdat_end}"[dp])'
            raise ValueError(f"Unsupported date_field={date_field!r}; expected 'DP' or 'EDAT'")

        async def _collect_pmids_by_uid_range(
            base_query: str,
            *,
            uid_range: Optional[Tuple[int, int]] = None,
            depth: int = 0,
        ) -> List[str]:
            """当无法按日期拆分时，使用 UID/PMID 数值区间递归拆分获取全部 PMID。"""
            query_with_uid = base_query
            if uid_range is not None:
                lo, hi = uid_range
                query_with_uid = f"{base_query} AND {lo}:{hi}[uid]"

            _, total_count = await self.pubmed.search(
                query_with_uid,
                retmax=1,
                retstart=0,
                use_cache=True,
                return_count=True,
            )
            total_count = int(total_count or 0)
            if total_count <= 0:
                return []

            if total_count <= 9999:
                return await self.pubmed.search(
                    query_with_uid,
                    retmax=min(total_count, 9999),
                    retstart=0,
                    use_cache=True,
                )

            if uid_range is None:
                uid_range = (0, 999_999_999)
            lo, hi = uid_range
            if lo >= hi:
                raise RuntimeError(
                    f"PubMed hit count {total_count} > 9999 but cannot split further: uid_range={uid_range}"
                )
            mid = (lo + hi) // 2
            left_range = (lo, mid)
            right_range = (mid + 1, hi)
            print(
                f"⚠️  PubMed命中 {total_count:,} > 9,999，自动拆分UID区间: "
                f"{left_range[0]}~{left_range[1]} + {right_range[0]}~{right_range[1]}"
            )
            left_ids = await _collect_pmids_by_uid_range(
                base_query,
                uid_range=left_range,
                depth=depth + 1,
            )
            right_ids = await _collect_pmids_by_uid_range(
                base_query,
                uid_range=right_range,
                depth=depth + 1,
            )
            return list(dict.fromkeys(left_ids + right_ids))

        async def _collect_pmids(
            sub_start: datetime,
            sub_end: datetime,
            *,
            uid_range: Optional[Tuple[int, int]] = None,
            depth: int = 0,
        ) -> List[str]:
            sub_filter = _build_date_filter(sub_start, sub_end)
            sub_query = f"{SPORTS_GATE} AND {sub_filter}"
            if uid_range is not None:
                lo, hi = uid_range
                sub_query = f"{sub_query} AND {lo}:{hi}[uid]"

            _, total_count = await self.pubmed.search(
                sub_query,
                retmax=1,
                retstart=0,
                use_cache=True,
                return_count=True,
            )
            total_count = int(total_count or 0)
            if total_count <= 0:
                return []

            if total_count <= 9999:
                # PubMed ESearch 对 PubMed 数据库最多只能返回前 9,999 个 ID
                # 这里保证 retstart=0 且 retmax<=9999，避免触发 retstart 限制报错
                return await self.pubmed.search(
                    sub_query,
                    retmax=min(total_count, 9999),
                    retstart=0,
                    use_cache=True,
                )

            # total_count > 9999：自动拆分（日期/UID区间）直到每段 <= 9999
            if date_field_norm == "DP":
                s_date = sub_start.date()
                e_date = sub_end.date()
                if s_date < e_date:
                    days = (e_date - s_date).days
                    mid_date = s_date + timedelta(days=days // 2)
                    tzinfo = sub_start.tzinfo
                    left_end = datetime(mid_date.year, mid_date.month, mid_date.day, tzinfo=tzinfo)
                    right_start_date = mid_date + timedelta(days=1)
                    right_start = datetime(
                        right_start_date.year,
                        right_start_date.month,
                        right_start_date.day,
                        tzinfo=tzinfo,
                    )
                    print(
                        f"⚠️  PubMed命中 {total_count:,} > 9,999，自动拆分DP窗口: "
                        f"{s_date.isoformat()}~{mid_date.isoformat()} + {right_start_date.isoformat()}~{e_date.isoformat()}"
                    )
                    left_ids = await _collect_pmids(sub_start, left_end, uid_range=uid_range, depth=depth + 1)
                    right_ids = await _collect_pmids(right_start, sub_end, uid_range=uid_range, depth=depth + 1)
                    return list(dict.fromkeys(left_ids + right_ids))

            if date_field_norm == "EDAT":
                if sub_start < sub_end:
                    if (sub_end - sub_start) > timedelta(seconds=1):
                        mid = sub_start + (sub_end - sub_start) / 2
                        mid = mid.replace(microsecond=0)
                        right_start = mid + timedelta(seconds=1)
                        print(
                            f"⚠️  PubMed命中 {total_count:,} > 9,999，自动拆分EDAT窗口: "
                            f"{sub_start.isoformat()}~{mid.isoformat()} + {right_start.isoformat()}~{sub_end.isoformat()}"
                        )
                        left_ids = await _collect_pmids(sub_start, mid, uid_range=uid_range, depth=depth + 1)
                        right_ids = await _collect_pmids(right_start, sub_end, uid_range=uid_range, depth=depth + 1)
                        return list(dict.fromkeys(left_ids + right_ids))

            # 日期维度无法继续拆分：按 UID/PMID 数值区间递归拆分
            if uid_range is None:
                uid_range = (0, 999_999_999)
            lo, hi = uid_range
            if lo >= hi:
                raise RuntimeError(
                    f"PubMed hit count {total_count} > 9999 but cannot split further: uid_range={uid_range}"
                )
            mid = (lo + hi) // 2
            left_range = (lo, mid)
            right_range = (mid + 1, hi)
            print(
                f"⚠️  PubMed命中 {total_count:,} > 9,999，自动拆分UID区间: "
                f"{left_range[0]}~{left_range[1]} + {right_range[0]}~{right_range[1]}"
            )
            left_ids = await _collect_pmids(sub_start, sub_end, uid_range=left_range, depth=depth + 1)
            right_ids = await _collect_pmids(sub_start, sub_end, uid_range=right_range, depth=depth + 1)
            return list(dict.fromkeys(left_ids + right_ids))
        
        # 2. 搜索PMID（分批获取，突破9999限制）
        print(f"📚 检索PubMed...")

        # 使用 start/end 信息（如果有）进行自动拆分，避免 PubMed ESearch 的 9,999 限制
        if start_utc and end_utc:
            pmids = await _collect_pmids(start_utc, end_utc)
        else:
            # 兜底：无法提供 start/end 时，用 UID 区间递归拆分保证每段 <= 9,999
            _, total_count = await self.pubmed.search(
                query,
                retmax=1,
                retstart=0,
                use_cache=True,
                return_count=True,
            )
            total_count = int(total_count or 0)
            if total_count > 9999:
                pmids = await _collect_pmids_by_uid_range(query)
            else:
                pmids = await self.pubmed.search(query, retmax=min(total_count, 9999), retstart=0, use_cache=True)

        total_count = len(pmids)
        print(f"✅ 总共找到 {total_count:,} 篇文献\n")

        if total_count == 0:
            return {
                'total_processed': 0,
                'new_count': 0,
                'duplicates_skipped': 0
            }

        # 2.5 过滤掉数据库中已存在的PMID（提前去重，避免重复爬取）
        print(f"🔍 检查数据库中已存在的文献...")
        existing_pmids_result = await self.db.execute(
            select(Literature.pmid).where(Literature.pmid.in_(pmids))
        )
        existing_pmids = set(row[0] for row in existing_pmids_result.fetchall())

        original_count = len(pmids)
        pmids = [p for p in pmids if p not in existing_pmids]
        duplicates_skipped = original_count - len(pmids)

        print(f"   已存在: {duplicates_skipped:,} 篇（跳过）")
        print(f"   待爬取: {len(pmids):,} 篇\n")

        if len(pmids) == 0:
            print(f"✅ 所有文献已存在于数据库中，无需爬取\n")
            return {
                'total_processed': original_count,
                'new_count': 0,
                'duplicates_skipped': duplicates_skipped
            }

        # 3. 分批获取文献详情（混合重试策略）
        print(f"📖 获取文献详情（含摘要）...")
        print(f"   总计: {len(pmids):,}篇")
        print(f"   预计耗时: {len(pmids)*0.4/3600:.1f}小时")
        print(f"   重试策略: 快速重试2次 → 跳过 → 批次结束后完整重试\n")

        batch_size = 50
        all_articles = []
        failed_pmids_with_summary = []  # 记录失败的PMID和摘要信息
        start_time = datetime.now()

        for i in range(0, len(pmids), batch_size):
            batch_pmids = pmids[i:i+batch_size]
            batch_start = datetime.now()

            # 获取摘要信息
            summaries = await self.pubmed.fetch_summary(batch_pmids, use_cache=True)
            # fetch_summary 可能因 PMID 不存在/异常导致返回子集；用映射避免 zip 错位
            summary_map = {
                s.get("pmid"): s for s in (summaries or []) if isinstance(s, dict) and s.get("pmid")
            }

            # 批量 efetch 获取完整摘要 + PublicationType + MeSH术语（显著减少网络往返）
            details_map: Dict[str, Tuple[Optional[str], list[str], list[str]]] = {}
            try:
                details_map = await self.pubmed.fetch_abstract_and_types_batch(batch_pmids, use_cache=False)
            except Exception as e:
                details_map = {}
                print(f"   ⚠️  批量efetch失败，回退单篇efetch: {type(e).__name__}")

            for pmid in batch_pmids:
                summary = summary_map.get(pmid, {})
                abstract, pub_types, mesh_terms = None, [], []
                fetch_success = False

                if pmid in details_map:
                    abstract, pub_types, mesh_terms = details_map[pmid]
                    fetch_success = True
                else:
                    # 回退到单篇 efetch（快速重试2次）
                    for retry in range(2):
                        try:
                            abstract, pub_types, mesh_terms = await self.pubmed.fetch_abstract_and_types(pmid)
                            fetch_success = True
                            break
                        except Exception as e:
                            if retry == 0:
                                await asyncio.sleep(2)
                            else:
                                failed_pmids_with_summary.append((pmid, summary))
                                if len(failed_pmids_with_summary) <= 10:
                                    print(f"   ⚠️  [{pmid}] 暂时跳过（稍后重试）: {type(e).__name__}")

                # 即使失败也创建文章对象（批次结束后重试）
                article = {
                    'pmid': pmid,
                    'title': summary.get('title', ''),
                    'abstract': abstract,
                    'authors': summary.get('authors', []),
                    'journal_name': summary.get('source', ''),
                    'publication_date': summary.get('pubdate', ''),
                    'doi': summary.get('doi', ''),
                    # 新增：文献类型判断所需字段
                    'publication_types': pub_types,
                    'mesh_terms': mesh_terms,
                    '_fetch_failed': not fetch_success,  # 标记是否获取失败
                }
                all_articles.append(article)

            # 详细进度日志
            batch_time = (datetime.now() - batch_start).total_seconds()
            total_processed = len(all_articles)
            progress_pct = total_processed / len(pmids) * 100
            elapsed = (datetime.now() - start_time).total_seconds()

            # 预估剩余时间
            if total_processed > 0:
                avg_time_per_article = elapsed / total_processed
                remaining = len(pmids) - total_processed
                eta_seconds = remaining * avg_time_per_article
                eta_minutes = eta_seconds / 60
                eta_hours = eta_minutes / 60

                if eta_hours >= 1:
                    eta_str = f"{eta_hours:.1f}小时"
                else:
                    eta_str = f"{eta_minutes:.1f}分钟"
            else:
                eta_str = "计算中..."

            # 每批都输出进度
            failed_count = len(failed_pmids_with_summary)
            status_str = f" | 失败: {failed_count}" if failed_count > 0 else ""
            print(f"   [{total_processed:,}/{len(pmids):,}] {progress_pct:5.1f}% | "
                  f"本批耗时: {batch_time:.1f}秒 | 剩余: {eta_str}{status_str}")

            await asyncio.sleep(0.3)

        print(f"✅ 第一阶段完成: {len(all_articles):,}篇")

        # 4. 批次结束后重试失败的文献（完整指数退避）
        if failed_pmids_with_summary:
            print(f"\n🔄 重试失败的 {len(failed_pmids_with_summary)} 篇文献（完整重试策略）...")
            retry_start = datetime.now()
            retry_success = 0
            retry_failed = 0

            failed_pmids = [pmid for pmid, _ in failed_pmids_with_summary]
            # 批量重试（仍失败的再回退单篇）
            for j in range(0, len(failed_pmids), 50):
                chunk_pmids = failed_pmids[j:j+50]
                try:
                    retry_map = await self.pubmed.fetch_abstract_and_types_batch(chunk_pmids, use_cache=False)
                except Exception:
                    retry_map = {}

                for pmid in chunk_pmids:
                    try:
                        if pmid in retry_map:
                            abstract, pub_types, mesh_terms = retry_map[pmid]
                        else:
                            abstract, pub_types, mesh_terms = await self.pubmed.fetch_abstract_and_types(pmid)

                        for article in all_articles:
                            if article['pmid'] == pmid:
                                article['abstract'] = abstract
                                article['publication_types'] = pub_types
                                article['mesh_terms'] = mesh_terms
                                article['_fetch_failed'] = False
                                break
                        retry_success += 1

                    except Exception as e:
                        retry_failed += 1
                        if retry_failed <= 5:
                            print(f"   ❌ [{pmid}] 重试失败: {type(e).__name__}: {str(e)[:50]}")

            retry_time = (datetime.now() - retry_start).total_seconds()
            print(f"✅ 重试完成: 成功 {retry_success}/{len(failed_pmids_with_summary)} | "
                  f"失败 {retry_failed} | 耗时 {retry_time:.1f}秒")

            # 过滤掉仍然失败的文章
            original_count = len(all_articles)
            all_articles = [a for a in all_articles if not a.get('_fetch_failed', False)]
            filtered = original_count - len(all_articles)
            if filtered > 0:
                print(f"⚠️  过滤掉 {filtered} 篇无法获取摘要的文章\n")

        print(f"\n✅ 获取完成: {len(all_articles):,}篇（有效数据）\n")

        # 4. 相关性过滤（64并发，阈值0.25）
        print(f"🔍 运动科学相关性过滤（64并发）...")
        print(f"   阈值: ≥0.25 保留，<0.25 过滤\n")

        try:
            relevance_concurrent = int(os.getenv("LLM_RELEVANCE_MAX_CONCURRENT", "64"))
        except Exception:
            relevance_concurrent = 64

        relevant_articles = await self._filter_by_relevance(
            all_articles,
            threshold=0.25,
            max_concurrent=relevance_concurrent
        )

        if len(relevant_articles) == 0:
            print(f"⚠️  相关性过滤后无文章，跳过后续分类\n")
            return {
                'total_processed': len(all_articles),
                'new_count': 0,
                'duplicates_skipped': 0,
                'filtered_by_relevance': len(all_articles),
                'category_stats': {},
                'lit_type_stats': {},
            }

        # 5. LLM分类（仅对通过相关性过滤的文章）
        print(f"🤖 DeepSeek分类中（{len(relevant_articles):,}篇）...")
        print(f"   使用: 标题 + 摘要前100字")
        print(f"   批处理: 每批20篇\n")

        classifications = await self.llm_classifier.classify_batch(
            relevant_articles,
            batch_size=20
        )

        print(f"✅ 分类完成\n")

        # 6. 合并结果
        classified_articles = self.llm_classifier.merge_results(
            relevant_articles,
            classifications
        )

        # 5.1 原创研究二分类（动物 vs 人体/理论，LLM）
        originals_for_llm: List[Dict[str, Any]] = []
        for article in classified_articles:
            # 先用规则划掉 meta/review/guideline
            rule_types = self._classify_literature_type(
                pub_types=article.get('publication_types', []),
                mesh_terms=article.get('mesh_terms', [])
            )
            if rule_types and rule_types[0] in ['meta_analysis', 'review', 'guideline']:
                article['literature_types'] = rule_types
            else:
                originals_for_llm.append(article)

        if originals_for_llm:
            try:
                classifier = get_animal_classifier()
                originals_classified = await classifier.classify_batch(
                    originals_for_llm,
                    batch_size=64
                )
                for article in originals_classified:
                    article['literature_types'] = (
                        ['original_animal'] if article.get('is_animal') else ['original_human']
                    )
            except Exception as e:
                # LLM失败时回退到规则分类，保证不中断主流程
                print(f"⚠️  原创研究LLM二分类失败，回退规则: {e}")
                for article in originals_for_llm:
                    article['literature_types'] = self._classify_literature_type(
                        pub_types=article.get('publication_types', []),
                        mesh_terms=article.get('mesh_terms', [])
                    )

        # 确保每篇文章都有文献类型（LLM/规则都未命中时兜底）
        for article in classified_articles:
            if not article.get('literature_types'):
                article['literature_types'] = self._classify_literature_type(
                    pub_types=article.get('publication_types', []),
                    mesh_terms=article.get('mesh_terms', [])
                )
        
        # 7. 保存到数据库
        print(f"💾 保存到数据库...")
        saved_count = 0
        skipped_count = 0
        date_parse_failed_count = 0
        new_pmids_for_translation: list[str] = []

        # 提交频率可配置：大规模回填/重建时可适当调大以减少 commit 开销
        try:
            commit_every = int(os.getenv("LITERATURE_SAVE_COMMIT_EVERY", "100"))
        except Exception:
            commit_every = 100
        if commit_every <= 0:
            commit_every = 100
        
        for idx, article in enumerate(classified_articles):
            # 检查是否已存在（提前过滤 + 运行中新增都记录到集合里，避免每篇都查DB）
            if article['pmid'] in existing_pmids:
                skipped_count += 1
                continue
            
            # 期刊匹配
            journal_info = await self.journal_matcher.match_journal(
                issn=None,
                journal_name=article['journal_name']
            )

            # 文献类型规则分类
            lit_types = article.get('literature_types') or self._classify_literature_type(
                pub_types=article.get('publication_types', []),
                mesh_terms=article.get('mesh_terms', [])
            )

            # 解析发表日期（失败时留空，不默认今天）
            pub_date = None
            if article['publication_date']:
                try:
                    pub_date = date_parser.parse(article['publication_date']).date()
                except Exception as e:
                    date_parse_failed_count += 1
                    # 仅前10个失败记录输出详情，避免刷屏
                    if date_parse_failed_count <= 10:
                        print(f"   ⚠️  日期解析失败 [PMID={article['pmid']}]: '{article['publication_date']}' - {e}")

            # 创建文献记录
            lit = Literature(
                pmid=article['pmid'],
                title=article['title'],
                abstract=article['abstract'],
                authors=article['authors'],
                publication_date=pub_date,
                journal_name=article['journal_name'],
                journal_issn=journal_info.get('issn'),
                journal_nlm_abbr=journal_info.get('nlm_abbr'),
                journal_if_5y=journal_info.get('if_5y'),
                journal_citescore=journal_info.get('citescore'),
                journal_zone=journal_info.get('zone'),
                doi=article['doi'],
                subject_categories=article.get('subject_categories', []),
                literature_types=lit_types,  # 修复：使用规则分类结果
                extra_metadata={
                    'classification_confidence': article.get('classification_confidence', []),
                    'primary_category': article.get('primary_category'),
                    # 记录分类依据
                    'publication_types': article.get('publication_types', []),
                    'mesh_terms': article.get('mesh_terms', []),
                    'is_animal': article.get('is_animal'),
                }
            )
            
            self.db.add(lit)
            saved_count += 1
            new_pmids_for_translation.append(article['pmid'])
            existing_pmids.add(article['pmid'])
            
            # 每100篇提交一次
            if saved_count % commit_every == 0:
                await self.db.commit()
                print(f"   已保存: {saved_count:,}/{len(classified_articles):,}")
        
        await self.db.commit()
        print(f"✅ 保存完成: {saved_count:,}篇")
        if date_parse_failed_count > 0:
            print(f"   ⚠️  日期解析失败: {date_parse_failed_count:,}篇（已留空，不默认今天）\n")
        else:
            print()

        # 8. 分类统计
        category_stats = {}
        lit_type_stats = {}
        for article in classified_articles:
            # 学科分类统计
            for cat in article.get('subject_categories', []):
                category_stats[cat] = category_stats.get(cat, 0) + 1

            # 文献类型统计
            lit_types = article.get('literature_types') or self._classify_literature_type(
                pub_types=article.get('publication_types', []),
                mesh_terms=article.get('mesh_terms', [])
            )
            for lit_type in lit_types:
                lit_type_stats[lit_type] = lit_type_stats.get(lit_type, 0) + 1

        print(f"{'='*80}")
        print(f"📊 学科分类统计")
        print(f"{'='*80}")
        for key, count in sorted(category_stats.items(), key=lambda x: -x[1]):
            cat_name = self.llm_classifier.CATEGORIES.get(key, key)
            percentage = count / len(classified_articles) * 100
            print(f"  {cat_name:20s}: {count:5,}篇 ({percentage:5.1f}%)")

        print(f"\n{'='*80}")
        print(f"📚 文献类型统计")
        print(f"{'='*80}")
        lit_type_names = {
            'meta_analysis': 'Meta分析&系统综述',
            'review': '综述',
            'guideline': '指南/共识/Protocol',
            'original_animal': '原创研究-动物',
            'original_human': '原创研究-人体/理论',
        }
        for key, count in sorted(lit_type_stats.items(), key=lambda x: -x[1]):
            type_name = lit_type_names.get(key, key)
            percentage = count / len(classified_articles) * 100
            print(f"  {type_name:25s}: {count:5,}篇 ({percentage:5.1f}%)")

        print(f"{'='*80}\n")

        # 9. 增量任务：为新增文献自动翻译标题（仅对每日上新等增量任务启用）
        # 避免在大规模回填任务中产生额外成本
        try:
            if new_pmids_for_translation and (task_log.task_type or "").startswith("incremental"):
                from core.services.batch_translator import BatchTranslator

                print(f"🈶 自动翻译新增文献标题（{len(new_pmids_for_translation):,}篇）...")
                translator = BatchTranslator()
                # 后续调用内部已经带有缓存逻辑，已翻译的不会重复请求
                # BatchTranslator 单次最多处理 50 条，这里分批覆盖全部新增标题
                pmids_unique = list(dict.fromkeys(new_pmids_for_translation))
                for i in range(0, len(pmids_unique), 50):
                    await translator.translate_titles_for_literature(pmids_unique[i : i + 50], self.db)
                print("✅ 自动翻译完成\n")
        except Exception as e:
            # 翻译失败不影响主流程，只记录日志
            print(f"⚠️ 自动翻译标题失败（忽略，不中断主流程）: {e}")

        return {
            'total_processed': original_count,  # 原始PMID总数
            'filtered_by_relevance': len(all_articles) - len(relevant_articles),
            'new_count': saved_count,
            'duplicates_skipped': duplicates_skipped + skipped_count,  # 提前过滤 + 保存时跳过
            'category_stats': category_stats,
            'lit_type_stats': lit_type_stats,
        }
