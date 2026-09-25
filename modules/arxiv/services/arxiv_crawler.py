"""
arXiv爬取服务
L1层：arXiv API查询 + 关键词批次查询
"""
import re
import time
import logging
from datetime import datetime, date
from typing import List, Dict, Set
import arxiv

logger = logging.getLogger(__name__)

# arXiv分类（用于先缩小到更可能包含“运动科学 × 生物/医学/AI”预印本的范围）
ARXIV_CATEGORIES = [
    "q-bio.NC",      # 神经科学
    "q-bio.QM",      # 定量方法
    "q-bio.TO",      # 组织、器官和生物体
    "physics.bio-ph", # 生物物理
    "physics.med-ph", # 医学物理
    "cs.AI",          # 人工智能
    "cs.CL",          # 计算语言学 / LLM（重要：RAG/LLM 相关论文常在该类）
    "cs.LG",          # 机器学习
    "cs.CV",          # 计算机视觉
    "cs.HC",          # 人机交互
    "cs.IR",          # 信息检索（RAG/检索常见）
    "stat.AP",        # 统计应用
    "stat.ML",        # 统计机器学习
    "eess.SP",        # 信号处理
]

# 236个运动科学关键词（精准短语）
SPORTS_KEYWORDS = [
    # 核心精准词
    "sport", "sports", "athlete", "athletic", "athletics",
    "exercise", "physical activity", "exercise training",

    # 训练相关
    "athletic training", "sport training",
    "strength training", "endurance training", "resistance training",
    "interval training", "circuit training", "plyometric training",
    "sport-specific training", "periodization training",
    "athletic performance", "sport performance", "exercise performance",
    "sports coaching", "athletic coaching", "coaching strategy",
    "athlete training load", "external training load", "internal training load",
    "training adaptation",

    # 能力与素质
    "muscular strength", "aerobic capacity", "anaerobic capacity",
    "cardiorespiratory fitness", "aerobic fitness", "cardiovascular fitness",
    "running speed", "sprint speed", "athletic speed",
    "power output", "muscle power", "explosive power", "peak power",
    "motor skill", "athletic agility", "movement skill",
    "flexibility training", "range of motion",
    "maximal strength", "muscle endurance", "muscular endurance",
    "jump performance", "vertical jump", "countermovement jump",

    # 运动类型
    "running performance", "endurance running", "trail running",
    "cycling performance", "road cycling", "mountain biking",
    "swimming performance", "open water swimming",
    "basketball performance", "football performance", "soccer performance",
    "tennis performance", "volleyball performance",
    "gymnastics performance", "weightlifting performance",
    "CrossFit athlete",
    "endurance sport", "team sport", "racket sport",
    "sprint running", "distance running", "marathon running",
    "competitive sport", "elite athlete", "recreational athlete",

    # 运动医学与康复
    "sport injury", "athletic injury", "exercise injury", "sports injury",
    "injury prevention", "injury risk", "injury mechanism",
    "sport rehabilitation", "athletic rehabilitation", "sports rehabilitation",
    "exercise recovery", "athletic recovery", "muscle recovery",
    "recovery strategy", "post-exercise recovery",
    "sports physiotherapy", "sports medicine", "sport medicine",
    "sports concussion", "concussion management",
    "ACL injury", "ACL tear", "ACL reconstruction",
    "muscle injury", "hamstring injury", "groin injury",
    "tendon injury", "tendinopathy", "Achilles tendon",
    "ligament injury", "ankle sprain",
    "muscle fatigue", "exercise fatigue", "athletic fatigue",
    "neuromuscular fatigue", "central fatigue", "peripheral fatigue",
    "overtraining syndrome", "overuse injury",
    "return to sport",

    # 运动生理学
    "exercise physiology", "sport physiology", "muscle physiology",
    "VO2max", "maximal oxygen uptake", "oxygen consumption",
    "lactate threshold", "anaerobic threshold", "ventilatory threshold",
    "heart rate variability", "exercise intensity",
    "muscle activation", "muscle contraction", "muscle fiber",
    "glycogen depletion", "substrate utilization",
    "thermoregulation", "heat stress", "cold exposure",

    # 运动生物力学
    "sports biomechanics", "exercise biomechanics",
    "running biomechanics", "gait biomechanics", "jumping biomechanics",
    "kinematic analysis", "kinetic analysis", "joint kinetics",
    "ground reaction force", "force platform",
    "stride length", "stride frequency", "contact time",
    "joint angle", "joint moment", "joint power",

    # 运动心理学
    "sport psychology", "exercise psychology", "sports psychology",
    "athletic performance psychology", "sport motivation",
    "mental training", "psychological skill",
    "athlete burnout", "sport anxiety",

    # 运动营养
    "sport nutrition", "sports nutrition", "exercise nutrition",
    "nutritional supplement", "dietary supplement",
    "ergogenic aid", "performance nutrition",
    "protein supplementation", "carbohydrate loading",

    # 测量与评估
    "motion capture", "motion analysis", "3D motion analysis",
    "video analysis", "performance analysis",
    "sports analytics", "athlete monitoring", "athlete tracking",
    "sport performance analysis", "athletic performance analysis",
    "performance testing", "fitness testing", "fitness assessment",
    "wearable sensor", "wearable device", "wearable technology",
    "GPS tracking", "accelerometer data", "inertial sensor",
    "force plate", "isokinetic dynamometer",

    # 运动控制与学习
    "kinesiology", "motor control", "motor learning", "motor skill",
    "skill acquisition", "motor development", "movement pattern",
    "neuromuscular control", "sensorimotor control",
    "movement variability", "movement coordination", "motor coordination",

    # 运动相关的动作与姿态
    "human movement", "human locomotion", "human gait",
    "running gait", "walking gait", "gait pattern",
    "gait analysis", "gait kinematics",
    "postural control", "postural balance", "postural stability",
    "balance control", "dynamic balance", "static balance",

    # 特定人群
    "young athlete", "youth athlete", "adolescent athlete",
    "master athlete", "older athlete", "veteran athlete",
    "female athlete", "male athlete",
    "Paralympic athlete", "disabled athlete",

    # 其他运动科学术语
    "physical education", "sport science", "exercise science",
    "sport performance enhancement",
    "talent identification", "talent development",
    "long-term athlete development",
]


class ArxivCrawler:
    """arXiv爬取器（L1层）"""

    def __init__(self, batch_size: int = 30):
        """
        初始化爬取器

        Args:
            batch_size: 关键词批次大小，默认30
        """
        self.batch_size = batch_size
        self.categories = ARXIV_CATEGORIES
        self.keywords = SPORTS_KEYWORDS

    def build_query(self, keyword_batch: List[str], date_from: str, date_to: str) -> str:
        """
        构建arXiv查询字符串

        Args:
            keyword_batch: 关键词列表（一个批次）
            date_from: 起始日期（YYYYMMDD格式）
            date_to: 结束日期（YYYYMMDD格式）

        Returns:
            查询字符串
        """
        # 构建分类过滤：(cat:q-bio.NC OR cat:q-bio.QM OR ...)
        cat_query = " OR ".join([f"cat:{cat}" for cat in self.categories])

        # 构建关键词查询：同时搜标题+摘要（ti/abs）
        # 形式： (ti:"kw" OR abs:"kw") OR (ti:"kw2" OR abs:"kw2") OR ...
        kw_query = " OR ".join([f'(ti:"{kw}" OR abs:"{kw}")' for kw in keyword_batch])

        # 日期过滤：submittedDate:[date_from TO date_to]
        date_query = f"submittedDate:[{date_from}0000 TO {date_to}2359]"

        # 完整查询
        query = f"({cat_query}) AND ({kw_query}) AND {date_query}"
        return query

    def fetch_batch(
        self,
        keyword_batch: List[str],
        date_from: str,
        date_to: str,
        max_results: int = 10000,
    ) -> List[Dict]:
        """
        查询一个关键词批次

        Args:
            keyword_batch: 关键词列表
            date_from: 起始日期（YYYYMMDD）
            date_to: 结束日期（YYYYMMDD）
            max_results: 最大结果数

        Returns:
            文章列表
        """
        query = self.build_query(keyword_batch, date_from, date_to)
        logger.info(f"L1查询批次：{len(keyword_batch)}个关键词，日期{date_from}-{date_to}")

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                search = arxiv.Search(
                    query=query,
                    max_results=max_results,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending,
                )

                results = []
                for result in search.results():
                    # 提取 short id（兼容 old-style: archive/YYMMNNN）
                    entry_id = (result.entry_id or "").strip()
                    short_id = entry_id.split("/abs/")[-1].strip()

                    # 解析版本号（末尾 vN），并去掉版本号得到稳定 arxiv_id
                    version = 1
                    m = re.search(r"v(\d+)$", short_id)
                    if m:
                        try:
                            version = int(m.group(1))
                        except ValueError:
                            version = 1
                        arxiv_id = short_id[: m.start()]
                    else:
                        arxiv_id = short_id

                    article = {
                        "arxiv_id": arxiv_id,
                        "version": version,
                        "source": "arxiv",
                        "title": result.title,
                        "abstract": result.summary,
                        "authors": [{"name": str(author)} for author in result.authors],
                        "primary_category": result.primary_category,
                        "categories": result.categories,
                        "published_date": result.published.date(),
                        "updated_date": result.updated.date(),
                        "submitted_date": result.published.date(),  # arXiv没有单独的submitted_date字段
                        "pdf_url": result.pdf_url,
                        "abs_url": result.entry_id,
                    }
                    results.append(article)

                logger.info(f"L1召回：{len(results)}篇文章")
                return results

            except Exception as e:
                last_error = e
                logger.error(f"arXiv查询失败（第{attempt + 1}/3次尝试）: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

        if last_error:
            raise last_error
        return []

    def deduplicate_by_arxiv_id(self, articles: List[Dict]) -> List[Dict]:
        """
        按arxiv_id去重，保留最新版本

        Args:
            articles: 文章列表

        Returns:
            去重后的文章列表
        """
        article_map: Dict[str, Dict] = {}

        for article in articles:
            arxiv_id = article["arxiv_id"]
            version = article.get("version", 1)

            if arxiv_id not in article_map:
                article_map[arxiv_id] = article
            else:
                # 比较版本号，保留最新
                existing_version = article_map[arxiv_id].get("version", 1)
                if version > existing_version:
                    article_map[arxiv_id] = article

        deduped = list(article_map.values())
        logger.info(f"去重后：{len(deduped)}篇文章（去重前{len(articles)}篇）")
        return deduped

    def crawl_date_range(
        self, date_from: date, date_to: date, batch_delay: int = 5
    ) -> List[Dict]:
        """
        爬取指定日期范围的文章（分批查询）

        Args:
            date_from: 起始日期
            date_to: 结束日期
            batch_delay: 批次间延迟（秒），默认5秒

        Returns:
            去重后的文章列表
        """
        # 将关键词分批
        keyword_batches = [
            self.keywords[i : i + self.batch_size]
            for i in range(0, len(self.keywords), self.batch_size)
        ]

        logger.info(
            f"L1爬取：{date_from}至{date_to}，共{len(self.keywords)}个关键词，"
            f"分{len(keyword_batches)}批，每批{self.batch_size}个"
        )

        all_articles = []
        date_from_str = date_from.strftime("%Y%m%d")
        date_to_str = date_to.strftime("%Y%m%d")

        for batch_idx, keyword_batch in enumerate(keyword_batches, 1):
            logger.info(f"处理批次 {batch_idx}/{len(keyword_batches)}")

            # 查询该批次
            batch_results = self.fetch_batch(keyword_batch, date_from_str, date_to_str)
            all_articles.extend(batch_results)

            # 批次间延迟（除了最后一批）
            if batch_idx < len(keyword_batches):
                logger.info(f"批次延迟{batch_delay}秒...")
                time.sleep(batch_delay)

        # 去重
        deduped_articles = self.deduplicate_by_arxiv_id(all_articles)
        return deduped_articles
