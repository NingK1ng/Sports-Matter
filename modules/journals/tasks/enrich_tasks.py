"""
Celery任务：PubMed 摘要补全

计划：
- 每日 04:30（UTC+8）执行，补齐前日新增与历史残留缺失摘要
"""

import asyncio
import os
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from celery import shared_task
from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.config import settings
from core.cache import init_cache
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, get_deepseek_client
from modules.journals.models.journal import JournalArticle, CrawlTaskLog
from modules.journals.services.abstract_fetcher import AbstractFetcher
from modules.journals.services.cns_sports_filter import build_candidate_tsquery_sql, DEFAULT_CNS_SPORTS_CANDIDATE_TERMS


async_engine = create_async_engine(
    settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@shared_task(name="journals_tracking.enrich_missing_abstracts")
def enrich_missing_abstracts(limit: int | None = None, concurrency: int | None = None) -> Dict[str, Any]:
    """
    批量补齐缺失摘要（优先新近文章）

    Args:
        limit: 最多处理多少篇（None=全量）
    """
    return asyncio.run(_async_enrich_missing_abstracts(limit))


async def _async_enrich_missing_abstracts(limit: int | None = None, concurrency: int | None = None) -> Dict[str, Any]:
    processed = 0
    updated = 0
    failed = 0
    batch_size = 2000  # 更大批次减少往返开销
    max_concurrency = concurrency or int(os.getenv("ENRICH_CONCURRENCY", "30"))
    ckpt_path = Path("logs") / "enrich_pubmed.ckpt.json"
    resume = os.getenv("ENRICH_RESUME", "1") != "0"
    reset = os.getenv("ENRICH_RESET", "0") == "1"

    try:
        await init_cache()
    except Exception:
        # 缓存可选
        pass

    # 处理checkpoint
    if reset and ckpt_path.exists():
        try:
            ckpt_path.unlink()
        except Exception:
            pass

    last_id_ckpt = 0
    if resume and ckpt_path.exists():
        try:
            data = json.loads(ckpt_path.read_text("utf-8"))
            last_id_ckpt = int(data.get("last_id", 0))
            processed = int(data.get("processed", 0))
            updated = int(data.get("updated", 0))
            failed = int(data.get("failed", 0))
        except Exception:
            last_id_ckpt = 0

    async with AsyncSessionLocal() as session:
        fetcher = AbstractFetcher()
        sem = asyncio.Semaphore(max_concurrency)

        last_id = last_id_ckpt
        # 高产过滤开关
        high_yield = os.getenv("ENRICH_HIGH_YIELD", "0") == "1"

        while True:
            # 按主键递增保证checkpoint可恢复
            # 默认跳过Nature新闻（低价值内容）
            base = select(JournalArticle).where(
                JournalArticle.id > last_id,
                (JournalArticle.abstract.is_(None)) | (JournalArticle.abstract == ''),
                ~JournalArticle.doi.like('10.1038/d41586-%'),  # 排除Nature新闻
                ~JournalArticle.doi.like('10.1038/s41586-0%'),  # 排除Nature短讯
            )

            if high_yield:
                # 期望更高命中：运动科学 + 生物医学CNS子刊
                from sqlalchemy import or_
                high_names = (
                    'Nature Medicine','Nature Neuroscience','Immunity',
                    'Nature Metabolism','Nature Methods','Science Advances','Cell'
                )
                base = base.where(
                    or_(
                        JournalArticle.category == 'sports_science',
                        JournalArticle.journal_name.in_(high_names),
                    )
                )

            stmt = base.order_by(JournalArticle.id.asc()).limit(batch_size)
            result = await session.execute(stmt)
            articles = result.scalars().all()
            if not articles:
                break

            async def work(art: JournalArticle):
                nonlocal updated, failed
                async with sem:
                    try:
                        result = await fetcher.ensure_abstract(
                            doi=art.doi,
                            crossref_abstract=None,
                            crossref_pmid=art.pmid,
                            landing_url=f"https://doi.org/{art.doi}" if art.doi else None,
                        )
                        if result.abstract:
                            return (art.id, result.pmid, result.abstract, result.source)
                        return None
                    except Exception:
                        failed += 1
                        return None

            # 并发抓取网络结果
            gathered = await asyncio.gather(*[work(art) for art in articles])
            to_update = [g for g in gathered if g]

            # 顺序写库（保证会话安全），分批提交
            for aid, pmid, abstract, source in to_update:
                try:
                    await session.execute(
                        update(JournalArticle)
                        .where(JournalArticle.id == aid)
                        .values(pmid=pmid, abstract=abstract, abstract_source=source, updated_at=datetime.utcnow())
                    )
                    updated += 1
                except Exception:
                    failed += 1

            await session.commit()

            # 记录 last_id（本批最大id）与进度
            last_id = articles[-1].id
            processed += len(articles)

            # 写checkpoint
            try:
                ckpt_path.parent.mkdir(parents=True, exist_ok=True)
                ckpt_path.write_text(json.dumps({
                    "last_id": last_id,
                    "processed": processed,
                    "updated": updated,
                    "failed": failed,
                    "timestamp": datetime.now().isoformat(),
                    "batch_size": batch_size,
                    "concurrency": max_concurrency,
                }, ensure_ascii=False), "utf-8")
            except Exception:
                pass

            if limit is not None and processed >= limit:
                break

    result_payload = {
        "timestamp": datetime.now().isoformat(),
        "processed": processed,
        "updated": updated,
        "failed": failed,
        "last_id": last_id,
    }

    try:
        await fetcher.close()
    except Exception:
        pass

    return result_payload


@shared_task(name="journals_tracking.classify_cns_sports_related")
def classify_cns_sports_related(
    limit: int | None = None,
    *,
    fetch_batch_size: int | None = None,
    llm_batch_size: int | None = None,
) -> Dict[str, Any]:
    """
    CNS 顶刊：运动相关预计算（规则召回候选 + LLM 判定，结果写入 extra_metadata.sports_related）

    - 规则召回：使用候选词表（支持单词/短语），在 title+abstract 的全文索引上做 OR 匹配；
    - LLM 判定：对候选集合做二分类，排除“模型训练/系统性能”等误召回，同时尽量不漏掉潜在相关；
    - 结果缓存：写入 journal_articles.extra_metadata，前端查询时只做 SQL 过滤。
    """
    return asyncio.run(_async_classify_cns_sports_related(limit, fetch_batch_size, llm_batch_size))


def _build_cns_sports_prompt(items: list[dict]) -> str:
    head = """任务：判断每篇文献是否属于“运动科学相关研究”(sports-science related)。

判 1（纳入）：
- 研究目标直接围绕：身体运动/体力活动/训练与竞技表现/运动损伤与康复/运动生理与生物力学/运动控制与技能学习等；
- 或者“身体运动/身体功能/活动水平/运动能力”是研究中的核心变量（暴露、干预、结局或主要测量）。

判 0（剔除）：
- “training / performance / fitness”仅表示算法训练、系统性能、进化适应度等（与身体运动无关）；
- “motor / movement / locomotion”指马达/电机/分子马达/蛋白马达，或机器人/材料/地质/气候等非生物体运动场景，且不用于理解或改善生物体运动功能；
- 与运动训练、竞技表现、运动损伤/康复、身体功能/活动水平无直接关系的研究。

规则：
- 不要依赖特定关键词（请按语义判断“研究问题/对象/变量”是否属于运动科学）；
- 仅依据提供的 title/abstract；abstract 为空时只看 title；
- 只输出 JSON：{"labels":[...]}（0/1），labels 长度必须等于输入条目数；
- 不要输出理由或除 JSON 以外任何文字；
- 不确定但“可能相关”时输出 1（宁可多纳入）。
"""
    lines = [head, "输入："]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}) {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines)


async def _call_deepseek_labels(items: list[dict], *, max_retries: int = 3) -> tuple[list[int], dict]:
    client = get_deepseek_client()
    prompt = _build_cns_sports_prompt(items)
    messages = [
        {"role": "system", "content": "You are a strict JSON classifier. Output JSON only."},
        {"role": "user", "content": prompt},
    ]

    last_err: Exception | None = None
    last_preview = ""
    for _ in range(max_retries):
        try:
            resp = await client.chat(
                messages,
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0,
                max_tokens=220,
                response_format={"type": "json_object"},
                return_message=True,
            )
            content = (resp or {}).get("content") or ""
            usage = (resp or {}).get("usage") or {}
            obj = json.loads(content)
            labels = obj.get("labels")
            if not isinstance(labels, list):
                raise ValueError("labels is not a list")
            if len(labels) != len(items):
                raise ValueError(f"labels length mismatch: {len(labels)} != {len(items)}")
            if any(int(x) not in (0, 1) for x in labels):
                raise ValueError("labels must be 0/1")
            return [int(x) for x in labels], usage
        except Exception as e:
            last_err = e
            try:
                last_preview = (content or "")[:200].replace("\n", " ")
            except Exception:
                last_preview = ""

    raise RuntimeError(f"DeepSeek classify failed: {last_err} preview={last_preview!r}")


async def _async_classify_cns_sports_related(
    limit: int | None = None,
    fetch_batch_size: int | None = None,
    llm_batch_size: int | None = None,
) -> Dict[str, Any]:
    processed = 0
    labeled_true = 0
    labeled_false = 0
    failed = 0
    run_processed = 0
    run_labeled_true = 0
    run_labeled_false = 0
    run_failed = 0

    fetch_batch_size = fetch_batch_size or int(os.getenv("CNS_SPORTS_FETCH_BATCH", "500"))
    llm_batch_size = llm_batch_size or int(os.getenv("CNS_SPORTS_LLM_BATCH", "50"))
    recent_days = int(os.getenv("CNS_SPORTS_RECENT_DAYS", "3") or "3")
    recent_max = int(os.getenv("CNS_SPORTS_RECENT_MAX", "500") or "500")

    ckpt_path = Path("logs") / "cns_sports_classifier.ckpt.json"
    resume = os.getenv("CNS_SPORTS_RESUME", "1") != "0"
    reset = os.getenv("CNS_SPORTS_RESET", "0") == "1"

    if reset and ckpt_path.exists():
        try:
            ckpt_path.unlink()
        except Exception:
            pass

    last_id = 0
    if resume and ckpt_path.exists():
        try:
            data = json.loads(ckpt_path.read_text("utf-8"))
            last_id = int(data.get("last_id", 0))
            processed = int(data.get("processed", 0))
            labeled_true = int(data.get("labeled_true", 0))
            labeled_false = int(data.get("labeled_false", 0))
            failed = int(data.get("failed", 0))
        except Exception:
            last_id = 0

    # 规则召回：构建 OR tsquery
    tsquery_sql, tsquery_params = build_candidate_tsquery_sql(
        DEFAULT_CNS_SPORTS_CANDIDATE_TERMS,
        param_prefix="t",
    )
    candidate_condition = text(f"(title_vector || abstract_vector) @@ ({tsquery_sql})")
    unlabeled_condition = text("(extra_metadata ->> 'sports_related') is null")

    cursor_id = last_id

    async with AsyncSessionLocal() as session:
        task_log = CrawlTaskLog(
            task_type="cns_sports_classify",
            issn_l=None,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        session.add(task_log)
        await session.commit()

        async def _finish_log(status: str, *, error_message: str | None = None):
            task_log.status = status
            task_log.finished_at = datetime.now(timezone.utc)
            task_log.total_fetched = run_processed
            task_log.new_inserted = run_labeled_true
            task_log.updated_count = run_labeled_false
            task_log.error_message = error_message
            await session.commit()

        try:
            # 1) 先补齐“近期入库”的未标注文章（不走候选词规则召回，保证每日可用）
            #    说明：sports_only 过滤会把 null 当作 false，因此必须尽快把近期文章标注成 true/false。
            if recent_days > 0 and recent_max > 0:
                recent_since = datetime.now(timezone.utc) - timedelta(days=recent_days)
                recent_processed = 0
                while True:
                    if limit is not None and processed >= limit:
                        break
                    if recent_processed >= recent_max:
                        break

                    stmt_recent = (
                        select(JournalArticle)
                        .where(
                            JournalArticle.category == "cns",
                            unlabeled_condition,
                            JournalArticle.created_at >= recent_since,
                        )
                        # 近期标注优先处理最新入库，避免被历史大批量入库挤占（影响“今日可用性”）
                        .order_by(JournalArticle.created_at.desc(), JournalArticle.id.desc())
                        .limit(fetch_batch_size)
                    )
                    recent_res = await session.execute(stmt_recent)
                    recent_articles = recent_res.scalars().all()
                    if not recent_articles:
                        break

                    for i in range(0, len(recent_articles), llm_batch_size):
                        if limit is not None and processed >= limit:
                            break
                        if recent_processed >= recent_max:
                            break
                        batch = recent_articles[i : i + llm_batch_size]
                        try:
                            items = [
                                {
                                    "id": int(art.id),
                                    "title": art.title or "",
                                    "abstract": (art.abstract or "")[:1200],
                                }
                                for art in batch
                            ]
                            labels, _usage = await _call_deepseek_labels(items)

                            now_iso = datetime.utcnow().isoformat()
                            for art, label in zip(batch, labels):
                                meta = art.extra_metadata or {}
                                meta["sports_related"] = bool(label)
                                meta["sports_related_model"] = DEEPSEEK_V4_FLASH_MODEL
                                meta["sports_related_at"] = now_iso
                                art.extra_metadata = meta
                                art.updated_at = datetime.utcnow()
                                if label == 1:
                                    labeled_true += 1
                                    run_labeled_true += 1
                                else:
                                    labeled_false += 1
                                    run_labeled_false += 1

                            await session.commit()
                            processed += len(batch)
                            run_processed += len(batch)
                            recent_processed += len(batch)
                        except Exception as e:
                            failed += len(batch)
                            run_failed += len(batch)
                            try:
                                await session.rollback()
                            except Exception:
                                pass
                            msg = str(e)
                            try:
                                msg = msg[:1000]
                            except Exception:
                                pass
                            await _finish_log("failed", error_message=msg)
                            return {
                                "timestamp": datetime.now().isoformat(),
                                "processed": processed,
                                "labeled_true": labeled_true,
                                "labeled_false": labeled_false,
                                "failed": failed,
                                "last_id": cursor_id,
                            }

            while True:
                stmt = (
                    select(JournalArticle)
                    .where(
                        JournalArticle.category == "cns",
                        JournalArticle.id > cursor_id,
                        unlabeled_condition,
                        candidate_condition,
                    )
                    .order_by(JournalArticle.id.asc())
                    .limit(fetch_batch_size)
                )

                result = await session.execute(stmt.params(**tsquery_params))
                articles = result.scalars().all()
                if not articles:
                    break

                # 按 LLM 批次处理并逐批提交，降低单次失败影响范围
                for i in range(0, len(articles), llm_batch_size):
                    batch = articles[i : i + llm_batch_size]
                    try:
                        items = []
                        for art in batch:
                            items.append(
                                {
                                    "id": int(art.id),
                                    "title": art.title or "",
                                    "abstract": (art.abstract or "")[:1200],
                                }
                            )

                        labels, _usage = await _call_deepseek_labels(items)

                        now_iso = datetime.utcnow().isoformat()
                        for art, label in zip(batch, labels):
                            meta = art.extra_metadata or {}
                            meta["sports_related"] = bool(label)
                            meta["sports_related_model"] = DEEPSEEK_V4_FLASH_MODEL
                            meta["sports_related_at"] = now_iso
                            art.extra_metadata = meta
                            art.updated_at = datetime.utcnow()
                            if label == 1:
                                labeled_true += 1
                                run_labeled_true += 1
                            else:
                                labeled_false += 1
                                run_labeled_false += 1

                        await session.commit()
                        processed += len(batch)
                        run_processed += len(batch)
                        cursor_id = int(batch[-1].id)
                    except Exception as e:
                        failed += len(batch)
                        run_failed += len(batch)
                        # 回滚本批并停止推进：留待下次重试，避免失败批次被 checkpoint 永久跳过
                        try:
                            await session.rollback()
                        except Exception:
                            pass
                        # 关键：不推进 checkpoint，避免“失败批次永久跳过”
                        try:
                            ckpt_path.parent.mkdir(parents=True, exist_ok=True)
                            ckpt_path.write_text(
                                json.dumps(
                                    {
                                        "last_id": cursor_id,
                                        "processed": processed,
                                        "labeled_true": labeled_true,
                                        "labeled_false": labeled_false,
                                        "failed": failed,
                                        "timestamp": datetime.now().isoformat(),
                                        "fetch_batch_size": fetch_batch_size,
                                        "llm_batch_size": llm_batch_size,
                                    },
                                    ensure_ascii=False,
                                ),
                                "utf-8",
                            )
                        except Exception:
                            pass
                        msg = str(e)
                        try:
                            msg = msg[:1000]
                        except Exception:
                            pass
                        await _finish_log("failed", error_message=msg)
                        return {
                            "timestamp": datetime.now().isoformat(),
                            "processed": processed,
                            "labeled_true": labeled_true,
                            "labeled_false": labeled_false,
                            "failed": failed,
                            "last_id": cursor_id,
                        }

                # checkpoint
                try:
                    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
                    ckpt_path.write_text(
                        json.dumps(
                            {
                                "last_id": cursor_id,
                                "processed": processed,
                                "labeled_true": labeled_true,
                                "labeled_false": labeled_false,
                                "failed": failed,
                                "timestamp": datetime.now().isoformat(),
                                "fetch_batch_size": fetch_batch_size,
                                "llm_batch_size": llm_batch_size,
                            },
                            ensure_ascii=False,
                        ),
                        "utf-8",
                    )
                except Exception:
                    pass

                if limit is not None and processed >= limit:
                    break

            # 即使无候选，也写一次checkpoint，避免“任务已跑但无痕迹”
            try:
                ckpt_path.parent.mkdir(parents=True, exist_ok=True)
                ckpt_path.write_text(
                    json.dumps(
                        {
                            "last_id": cursor_id,
                            "processed": processed,
                            "labeled_true": labeled_true,
                            "labeled_false": labeled_false,
                            "failed": failed,
                            "timestamp": datetime.now().isoformat(),
                            "fetch_batch_size": fetch_batch_size,
                            "llm_batch_size": llm_batch_size,
                        },
                        ensure_ascii=False,
                    ),
                    "utf-8",
                )
            except Exception:
                pass

            await _finish_log("success")
            return {
                "timestamp": datetime.now().isoformat(),
                "processed": processed,
                "labeled_true": labeled_true,
                "labeled_false": labeled_false,
                "failed": failed,
                "last_id": cursor_id,
            }
        except Exception as e:
            msg = str(e)
            try:
                msg = msg[:1000]
            except Exception:
                pass
            try:
                await _finish_log("failed", error_message=msg)
            except Exception:
                pass
            raise
