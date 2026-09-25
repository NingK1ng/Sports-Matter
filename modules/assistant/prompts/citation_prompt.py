"""
引用生成Prompt模板
任务2.2: Prompt设计与模板
"""
from typing import List
from modules.assistant.models.candidate import CandidateArticle


def build_citation_prompt(
    query: str,
    candidates: List[CandidateArticle],
    lang: str = "zh"
) -> str:
    """
    构建句级引用生成Prompt (使用JSON mode)
    
    Args:
        query: 用户查询
        candidates: 候选文献列表
        lang: 语言 zh|en
    
    Returns:
        完整的Prompt字符串
    """
    # 构建引用列表
    citations_list = []
    for idx, c in enumerate(candidates, start=1):
        abstract_preview = c.abstract[:500] + "..." if c.abstract and len(c.abstract) > 500 else (c.abstract or "")
        citations_list.append({
            "id": idx,
            "pmid": c.pmid,
            "title": c.title,
            "abstract": abstract_preview,
            "journal": c.journal_name or "N/A",
            "year": c.publication_year or "N/A",
            "url": c.url
        })
    
    import json
    citations_json = json.dumps(citations_list, ensure_ascii=False, indent=2)
    
    if lang == "zh":
        prompt = f"""你是该领域的资深专家。请基于下列文献撰写一篇小综述回答用户问题，以JSON格式输出。

**角色定位**：
你是研究该问题多年的领域专家，熟悉相关研究脉络和前沿进展。请用专家的视角和语气撰写综述性回答。

**核心要求**：
1. ⚠️ 必须使用中文撰写
2. 仅输出JSON格式（无Markdown包裹）
3. 基于文献事实，不编造数据，但可以进行学术性的解读、归纳和评述
4. 在每句话后用`citations`数组标注引用的文献编号（1-{len(candidates)}）

**写作风格**：
- 采用综述性叙述，可以有起承转合、背景铺垫、趋势总结
- 可以对多篇文献进行横向对比、纵向梳理
- 可以指出研究的异同点、争议、不足或未来方向
- 语言要流畅自然，像专家在讲述而非机械罗列
- 篇幅：6-12句话，根据内容需要自由调整

**引用规则**：
- 每句话必须标注引用来源
- 如果文献提供了具体数据（样本量、效应量等），可以引用
- 如果仅有标题和期刊，可描述研究方向和发表情况
- 可以多篇文献一起引用，如"多项研究表明..."[1,3,5]

**JSON格式**：
{{
  "sentences": [
    {{"text": "第一句话（专家视角的综述性叙述）", "citations": [1, 2]}},
    {{"text": "第二句话（可以是背景、趋势、对比等）", "citations": [3]}},
    ...
  ],
  "references": [
    {{"idx": 1, "pmid": "...", "title": "...", "journal": "...", "year": "...", "url": "..."}}
  ]
}}

**综述示例**（体会专家叙述风格）：
{{
  "sentences": [
    {{
      "text": "神经动力学作为神经科学的前沿交叉领域，近年来在理解大脑功能网络动态变化方面取得了重要进展。",
      "citations": [1, 3, 5]
    }},
    {{
      "text": "2024年发表于Int J Neuropsychopharmacol的研究开拓了药理学与神经动力学结合的新路径，为精神类药物的机制研究提供了创新性的方法学框架。",
      "citations": [1]
    }},
    {{
      "text": "在临床应用层面，Diagnostics期刊报道了神经动力学测序技术在周围神经评估中的应用价值，这为神经损伤的早期诊断提供了新的检测手段。",
      "citations": [3]
    }},
    {{
      "text": "值得关注的是，功能磁共振成像技术与神经动力学建模的结合正成为抑郁症等精神疾病客观诊断的重要方向，2025年Psychiatry Res Neuroimaging发表的预测模型研究代表了这一趋势。",
      "citations": [5]
    }},
    {{
      "text": "综合来看，神经动力学研究正从基础理论探索走向临床转化应用，但不同研究领域间的整合与标准化仍是当前面临的主要挑战。",
      "citations": [1, 3, 5]
    }}
  ],
  "references": [
    {{
      "idx": 1,
      "pmid": "12345678",
      "title": "Example title",
      "journal": "Example Journal",
      "year": "2024",
      "url": "https://example.com"
    }}
  ]
}}

**用户问题**：
{query}

**候选文献（引用编号与条目索引对应）**：
{citations_json}

请按照上述要求输出JSON："""
    else:
        prompt = f"""You are a literature-grounded assistant. Review the candidate papers and respond strictly with a valid json object.

**Requirements**:
1. Output raw JSON only (no narrative or markdown).
2. Provide a `sentences` array with 4-8 objects. Each object must include `text` and `citations`, e.g. `{{"text": "...", "citations": [1, 2]}}`.
3. Every sentence must address the user question and reference factual content (study design, sample size, effect magnitude, year, guideline, etc.). If evidence is missing, you may say once “available studies do not report this evidence” and cite the closest paper.
4. Do not assume a domain focus, user intent, or predefined structure; the question and supplied evidence should fully determine the answer.
5. `citations` must be an array of candidate indices (1-{len(candidates)}) in ascending order and deduplicated.
6. Include a `references` array mirroring the supplied candidate list when you cite them.
7. Never fabricate information or return an empty payload; if evidence is limited, state so while still emitting a complete JSON object.

**JSON Example**:
{{
  "sentences": [
    {{
      "text": "A 2024 randomized trial reported the intervention arm outperformed control on the primary endpoint.",
      "citations": [2]
    }},
    {{
      "text": "A 2023 living systematic review noted limited long-term safety data for aerobic rehabilitation.",
      "citations": [3]
    }}
  ],
  "references": [
    {{
      "idx": 1,
      "pmid": "12345678",
      "title": "Example title",
      "journal": "Example Journal",
      "year": "2024",
      "url": "https://example.com"
    }}
  ]
}}

**User Question**:
{query}

**Candidate Literature (indices map to citation markers)**:
{citations_json}

Return JSON that follows these rules."""
    
    return prompt


def build_json_fallback_prompt(
    query: str,
    candidates: List[CandidateArticle],
    lang: str = "zh"
) -> str:
    """
    构建JSON回退Prompt (Fallback阶段)
    
    Args:
        query: 用户查询
        candidates: 候选文献列表
        lang: 语言 zh|en
    
    Returns:
        JSON格式Prompt
    """
    import json

    citations_json_list = []
    for idx, c in enumerate(candidates, start=1):
        abstract_preview = c.abstract[:500] + "..." if c.abstract and len(c.abstract) > 500 else (c.abstract or "")
        citations_json_list.append({
            "idx": idx,
            "pmid": c.pmid,
            "title": c.title,
            "journal": c.journal_name or "N/A",
            "year": c.publication_year or "N/A",
            "abstract": abstract_preview,
            "url": c.url,
        })

    citations_json = json.dumps(citations_json_list, ensure_ascii=False, indent=2)
    
    if lang == "zh":
        prompt = f"""Primary阶段输出未通过校验，请以严格JSON重新生成答案。

**角色**：你是该领域的资深专家，请撰写一篇小综述回答问题。

**要求**：
1. ⚠️ 必须使用中文撰写
2. 仅输出纯JSON，不使用Markdown包裹
3. sentences数组包含6-12句话，采用综述性叙述风格
4. 每句话必须包含"text"与"citation_ids"，"citation_ids"为数组（1-{len(candidates)}）
5. 基于文献事实，不编造数据，但可以进行学术性解读和评述
6. 语言要流畅自然，像专家在讲述而非机械罗列
7. references数组需完整呈现候选文献信息

JSON示例（综述风格）：
{{
  "sentences": [
    {{
      "text": "运动损伤预防是运动科学领域长期关注的核心问题，近年来干预策略逐渐从单一手段转向多模态整合。",
      "citation_ids": [1, 3, 5]
    }},
    {{
      "text": "2024年Journal of Sports Science发表的渐进式负荷训练研究为损伤预防提供了新的证据支持，其长期随访数据特别值得关注。",
      "citation_ids": [2]
    }},
    {{
      "text": "值得注意的是，不同运动项目和人群的损伤风险因素存在显著差异，这提示预防方案需要个体化定制而非一刀切。",
      "citation_ids": [3, 5]
    }},
    {{
      "text": "当前研究的主要局限在于缺乏大样本多中心验证，以及对长期效果的追踪仍不充分。",
      "citation_ids": [2, 5]
    }}
  ],
  "references": [
    {{
      "idx": 1,
      "pmid": "12345678",
      "title": "Example title",
      "journal": "Example Journal",
      "year": "2024",
      "url": "https://example.com"
    }}
  ]
}}

用户问题：
{query}

候选文献：
{citations_json}

请直接输出满足上述要求的JSON："""
    else:
        prompt = f"""Primary output failed validation. Regenerate the answer as strict json and avoid returning empty content.

Requirements:
1. Return raw JSON only (no markdown).
2. The `sentences` array must contain 4-8 entries; fewer than 6 is allowed only if evidence is scarce.
3. Each sentence object must include "text" and "citation_ids"; "citation_ids" is an array of integers within 1-{len(candidates)}.
4. Sentences must stay on-topic, rely on the provided literature, and avoid assuming any specific domain or preset narrative; you may state once that evidence is absent (“available studies do not report this evidence”) while citing the closest paper.
5. Include a `references` array mirroring the candidate list so the server can verify citations.

JSON Example:
{{
  "sentences": [
    {{
      "text": "A 2024 randomized trial reported the intervention arm outperformed the control group on the primary outcome.",
      "citation_ids": [2]
    }},
    {{
      "text": "Available studies do not report long-term adverse event rates and further monitoring is required.",
      "citation_ids": [3]
    }}
  ],
  "references": [
    {{
      "idx": 1,
      "pmid": "12345678",
      "title": "Example title",
      "journal": "Example Journal",
      "year": "2024",
      "url": "https://example.com"
    }}
  ]
}}

User Question:
{query}

Candidate Literature:
{citations_json}

Return JSON that complies with these constraints:"""
    
    return prompt

