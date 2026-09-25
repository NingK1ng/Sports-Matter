"""
动物研究分类器 - DeepSeek LLM二分类
用于原创研究的子类判断：动物实验 vs 人体/理论研究
"""
import httpx
import json
import asyncio
import os
from typing import List, Dict, Any

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model


class AnimalClassifier:
    """动物研究分类器（LLM驱动）"""
    
    def __init__(self):
        self.api_key = os.getenv('LLM_API_KEY')
        self.base_url = os.getenv('LLM_BASE_URL', 'https://api.deepseek.com/v1')
        self.model = normalize_deepseek_model(os.getenv('LLM_MODEL', DEEPSEEK_V4_FLASH_MODEL))
        
        # 系统提示词：简洁精准，只判断是否为动物实验
        self.system_prompt = """你是运动科学文献分类专家。任务：判断原创研究是否为**动物实验**。

**动物实验特征**：
- 实验对象：小鼠、大鼠、兔、猪、羊、猴等非人类动物
- 常见表述：animal model, in vivo, rodent, murine, rat model, mouse model等

**人体/理论研究**：
- 实验对象：人类受试者（运动员、患者、志愿者等）
- 理论研究：无实验对象的理论分析、模型构建等

**输出格式**（严格JSON）：
```json
{"is_animal": true}  // 动物实验
{"is_animal": false} // 人体或理论研究
```

只输出JSON，不要解释。"""
    
    async def classify_batch(
        self,
        articles: List[Dict[str, Any]],
        batch_size: int = 64
    ) -> List[Dict[str, Any]]:
        """
        批量分类原创研究（动物 vs 人体/理论）
        
        Args:
            articles: 文献列表，每篇包含title和abstract
            batch_size: 批处理大小
            
        Returns:
            分类结果列表，每篇增加is_animal字段
        """
        if not articles:
            return []
        
        # 构建批量输入（缩短摘要以节省token）
        batch_input = []
        for idx, article in enumerate(articles):
            title = article.get('title', '')
            abstract = article.get('abstract', '')[:400]  # 前400字符足够判断
            
            batch_input.append(f"{idx+1}. Title: {title}\nAbstract: {abstract[:400]}")
        
        user_content = "请判断以下原创研究是否为动物实验：\n\n" + "\n\n".join(batch_input)
        user_content += f"\n\n输出格式：JSON数组，包含{len(articles)}个结果，例如：\n"
        user_content += '[{"is_animal": true}, {"is_animal": false}, ...]'
        
        # 调用DeepSeek API（带重试）
        max_retries = 2
        for retry in range(max_retries + 1):
            try:
                timeout_seconds = 90 if retry == 0 else 120
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": [
                                {"role": "system", "content": self.system_prompt},
                                {"role": "user", "content": user_content}
                            ],
                            "temperature": 0.1,  # 低温度，更确定性
                            "max_tokens": 4096,  # 增大以容纳64篇文章的JSON数组
                            "thinking": THINKING_DISABLED,
                        }
                    )
                
                response.raise_for_status()
                result = response.json()
                
                # 解析返回结果
                content = result['choices'][0]['message']['content'].strip()
                
                # 清理markdown代码块标记
                if content.startswith('```'):
                    lines = content.split('\n')
                    content = '\n'.join(lines[1:-1]) if len(lines) > 2 else content
                    content = content.replace('```json', '').replace('```', '').strip()
                
                classifications = json.loads(content)
                
                # 验证结果数量
                if len(classifications) != len(articles):
                    print(f"⚠️  返回结果数量不匹配：期望{len(articles)}，实际{len(classifications)}")
                    # 补全或截断
                    if len(classifications) < len(articles):
                        classifications.extend([{"is_animal": False}] * (len(articles) - len(classifications)))
                    else:
                        classifications = classifications[:len(articles)]
                
                # 合并结果到原始文章
                for article, classification in zip(articles, classifications):
                    article['is_animal'] = classification.get('is_animal', False)
                
                return articles
                
            except httpx.ReadTimeout as e:
                if retry < max_retries:
                    wait_time = 5 * (retry + 1)
                    print(f"⚠️  DeepSeek API超时，{wait_time}秒后重试 ({retry+1}/{max_retries})...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ DeepSeek API超时（90秒→120秒→120秒均失败）- 程序终止")
                    raise RuntimeError(f"DeepSeek API ReadTimeout after {max_retries} retries") from e
                    
            except httpx.HTTPStatusError as e:
                print(f"❌ DeepSeek API调用失败 (HTTP {e.response.status_code}): {e.response.text[:500]}")
                print(f"   程序终止")
                raise RuntimeError(f"DeepSeek API HTTP {e.response.status_code}") from e
                
            except json.JSONDecodeError as e:
                print(f"❌ 解析DeepSeek API返回JSON失败: {e}")
                print(f"   原始内容: {content[:500]}")
                # 尝试修复被截断的JSON
                try:
                    # 如果JSON被截断，尝试补全最后一个对象
                    if content.count('{') > content.count('}'):
                        # 缺少右括号，尝试补全
                        fixed_content = content.rstrip().rstrip(',')
                        while fixed_content.count('{') > fixed_content.count('}'):
                            fixed_content += '}'
                        if not fixed_content.endswith(']'):
                            fixed_content += ']'
                        classifications = json.loads(fixed_content)
                        print(f"   ✅ 已修复截断的JSON，解析成功")
                    else:
                        raise
                except:
                    print(f"   ⚠️  JSON修复失败，使用默认值（全部为human）")
                    # 失败时全部标记为非动物实验（保守策略）
                    classifications = [{"is_animal": False} for _ in articles]
                
                # 合并结果到原始文章（无论是修复成功还是使用默认值）
                for article, classification in zip(articles, classifications):
                    article['is_animal'] = classification.get('is_animal', False)
                
                return articles  # 返回结果，继续处理而不是抛出异常
                
            except Exception as e:
                if retry < max_retries:
                    wait_time = 5 * (retry + 1)
                    print(f"⚠️  DeepSeek API错误: {type(e).__name__}，{wait_time}秒后重试 ({retry+1}/{max_retries})...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ DeepSeek API调用失败（已重试{max_retries}次）: {type(e).__name__}: {e}")
                    print(f"   程序终止")
                    raise RuntimeError(f"DeepSeek API失败: {type(e).__name__}") from e
        
        # 不应该到达这里
        return articles


# 全局单例
_animal_classifier = None


def get_animal_classifier() -> AnimalClassifier:
    """获取动物分类器单例"""
    global _animal_classifier
    if _animal_classifier is None:
        _animal_classifier = AnimalClassifier()
    return _animal_classifier
