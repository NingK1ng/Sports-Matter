"""
WiW (What is What) Prompt 模板

用于生成研究空白分析的结构化输出
"""

def get_wiw_prompt(
    input_title: str,
    input_abstract: str,
    references: list[dict],
    language: str = "zh"
) -> str:
    """
    生成WiW分析的Prompt（仅支持中文）
    
    Args:
        input_title: 输入文献标题
        input_abstract: 输入文献摘要
        references: 相关文献列表 [{"pmid": str, "title": str, "abstract": str}, ...]
        language: 输出语言（仅zh，保留参数以兼容旧代码）
    
    Returns:
        str: 完整的Prompt文本
    """
    
    # 构建相关文献摘要文本
    references_text = ""
    for idx, ref in enumerate(references, 1):
        ref_abstract = ref.get("abstract", "（无摘要）")
        references_text += f"\n[文献{idx}] PMID: {ref['pmid']}\n标题: {ref['title']}\n摘要: {ref_abstract}\n"
    
    # 只支持中文提示词
    prompt = f"""你是该研究领域的资深专家。请基于输入文献和相关文献，以领域内专家的视角进行深入的研究空白分析。

# 输入文献
标题: {input_title}
摘要: {input_abstract}

# 相关文献（按相似度排序）
{references_text}

# 任务要求
请严格按照以下JSON格式输出分析结果（不要添加任何markdown标记或注释）：

{{
  "focus": "（不超过200字）当前研究的核心聚焦点是什么？请聚焦提炼，不要宽泛。**尽可能多综合文献**，以领域专家视角明确指出主要研究对象、核心方法和关键问题。",
  "next_questions": [
    "（不超过120字）第一个值得深入研究的关键问题。基于**多篇文献的综合分析**提出，避免只聚焦1-2篇。可适当引用文献作为支撑。",
    "（不超过120字）第二个值得深入研究的关键问题",
    "...（根据实际情况自主决定返回1-5个问题）"
  ],
  "conflicts": "（不超过300字）当前研究领域存在哪些争议或矛盾？**尽可能多综合文献**，识别不同研究之间的结论冲突。如果没有明显冲突，说明'当前研究方向基本一致'。可适当引用文献。",
  "gaps": [
    "（不超过120字）第一个研究空白点。**关键**：这不是单篇文献摘要结论中的limitations，而是**尽可能多综合召回文献后**，从领域专家视角发现的跨文献系统性空白、尚未充分探索的方向或未解决的问题。可适当引用文献，但避免过度依赖1-2篇。",
    "（不超过120字）第二个研究空白点",
    "...（根据实际情况自主决定返回1-5个空白点）"
  ]
}}

# 输出要求
1. 严格遵守JSON格式，确保可解析
2. 每个字段不得为空，不得使用null
3. 字数限制必须严格遵守
4. 内容必须基于文献事实，不得编造
5. 使用学术语言，简洁专业
6. 直接输出纯JSON对象，不要添加任何额外文字或markdown标记
"""
    
    return prompt


def get_wiw_system_prompt(language: str = "zh") -> str:
    """
    获取系统级Prompt（仅支持中文）
    
    Args:
        language: 输出语言（仅zh，保留参数以兼容旧代码）
    
    Returns:
        str: 系统Prompt
    """
    return "你是一位资深科学研究专家，擅长分析文献、识别研究空白和提出创新性研究问题。请以该文献所在领域的专家视角进行分析。你的分析必须基于事实，输出格式必须严格遵守JSON规范。"
