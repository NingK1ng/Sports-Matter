"""
对比测试：deepseek-v4-flash vs deepseek-v4-flash
测试两个模型在AI助手场景下的效果
"""
import asyncio
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.external.deepseek import DeepSeekClient

async def test_model_comparison():
    """对比两个模型的生成质量"""
    
    client = DeepSeekClient()
    
    # 模拟AI助手的Prompt（不使用JSON mode）
    query = "HIIT训练对心血管健康的影响"
    
    prompt = f"""你是运动科学文献助手。请基于以下文献回答问题，每句话必须标注引用[n]。

参考文献：
[1] High-intensity interval training improves cardiovascular health in rheumatoid arthritis patients
摘要：87名类风湿关节炎患者参与12周HIIT训练，VO2max显著提升，心肺功能改善明显...

[2] Comparison of HIIT vs MICT in obese adolescents
摘要：随机对照试验显示HIIT对肥胖青少年的心肺功能改善优于中等强度训练...

[3] Effects of HIIT on cardiometabolic health in overweight women
摘要：超重女性进行HIIT后抵抗素水平下降，心血管代谢指标改善...

规则：
1. 每句话末尾必须带[n]，n为参考文献编号（1-3）
2. 仅引用提供的参考文献，不得编造内容
3. 直接输出回答，不要JSON格式
4. 用中文回答

问题：{query}

回答："""

    messages = [{"role": "user", "content": prompt}]
    
    print("\n" + "="*80)
    print("🧪 模型对比测试：deepseek-v4-flash vs deepseek-v4-flash")
    print("="*80)
    print(f"\n📝 测试查询: {query}")
    print(f"📚 参考文献: 3篇")
    print("\n" + "-"*80)
    
    # 测试1: deepseek-v4-flash (当前使用)
    print("\n[测试1] deepseek-v4-flash (当前模型)")
    print("-"*80)
    
    start_time = time.time()
    try:
        response_chat = await client.chat(
            messages=messages,
            model="deepseek-v4-flash",
            temperature=0.3,
            max_tokens=1200,
            return_message=True
        )
        chat_duration = time.time() - start_time
        
        content = response_chat.get("content", "")
        reasoning = response_chat.get("reasoning", "")
        usage = response_chat.get("usage", {})
        
        print(f"✅ 生成成功")
        print(f"⏱️  耗时: {chat_duration:.2f}秒")
        print(f"📊 Token使用: prompt={usage.get('prompt_tokens', 0)}, " +
              f"completion={usage.get('completion_tokens', 0)}, " +
              f"total={usage.get('total_tokens', 0)}")
        print(f"\n💬 生成内容:")
        print("-"*80)
        print(content[:500] + "..." if len(content) > 500 else content)
        
        if reasoning:
            print(f"\n🧠 推理过程: {reasoning[:200]}...")
        
    except Exception as e:
        print(f"❌ 失败: {e}")
        chat_duration = time.time() - start_time
        content = ""
    
    # 测试2: deepseek-v4-flash (推理模型)
    print("\n" + "-"*80)
    print("\n[测试2] deepseek-v4-flash (推理模型)")
    print("-"*80)
    
    start_time = time.time()
    try:
        response_reasoner = await client.chat(
            messages=messages,
            model="deepseek-v4-flash",
            temperature=0.3,
            max_tokens=1200,
            return_message=True
        )
        reasoner_duration = time.time() - start_time
        
        content = response_reasoner.get("content", "")
        reasoning = response_reasoner.get("reasoning", "")
        usage = response_reasoner.get("usage", {})
        
        print(f"✅ 生成成功")
        print(f"⏱️  耗时: {reasoner_duration:.2f}秒")
        print(f"📊 Token使用: prompt={usage.get('prompt_tokens', 0)}, " +
              f"completion={usage.get('completion_tokens', 0)}, " +
              f"reasoning={usage.get('reasoning_tokens', 0)}, " +
              f"total={usage.get('total_tokens', 0)}")
        print(f"\n💬 生成内容:")
        print("-"*80)
        print(content[:500] + "..." if len(content) > 500 else content)
        
        if reasoning:
            print(f"\n🧠 推理过程 (前300字符):")
            print("-"*80)
            print(reasoning[:300] + "...")
        
    except Exception as e:
        print(f"❌ 失败: {e}")
        reasoner_duration = time.time() - start_time
    
    # 对比总结
    print("\n" + "="*80)
    print("📊 对比总结")
    print("="*80)
    print(f"{'模型':<20} {'耗时':<15} {'特点'}")
    print("-"*80)
    print(f"{'deepseek-v4-flash':<20} {chat_duration:>6.2f}秒{'':<7} 快速响应，直接生成")
    print(f"{'deepseek-v4-flash':<20} {reasoner_duration:>6.2f}秒{'':<7} 深度推理，质量更高")
    print(f"{'耗时差':<20} {reasoner_duration - chat_duration:>+6.2f}秒{'':<7} {'reasoner更慢' if reasoner_duration > chat_duration else 'reasoner更快'}")
    
    print("\n💡 建议:")
    if reasoner_duration > chat_duration * 2:
        print("  ⚠️  reasoner耗时明显更长，建议保持使用chat")
    elif reasoner_duration > chat_duration * 1.5:
        print("  💭 reasoner耗时稍长，需要权衡速度与质量")
    else:
        print("  ✅ reasoner耗时可接受，建议切换以提升质量")
    
    print("\n" + "="*80)


async def test_streaming_comparison():
    """测试流式生成对比"""
    
    client = DeepSeekClient()
    
    query = "HIIT训练对心血管健康的影响"
    
    prompt = f"""你是运动科学文献助手。请基于以下文献回答问题，每句话必须标注引用[n]。

参考文献：
[1] High-intensity interval training improves cardiovascular health
摘要：HIIT显著提升心肺功能和VO2max...

规则：
1. 每句话末尾必须带[n]
2. 直接输出回答，不要JSON格式
3. 用中文回答

问题：{query}

回答："""

    messages = [{"role": "user", "content": prompt}]
    
    print("\n" + "="*80)
    print("🧪 流式生成对比测试")
    print("="*80)
    
    # 测试流式chat
    print("\n[测试1] deepseek-v4-flash 流式生成")
    print("-"*80)
    
    start_time = time.time()
    chunks = []
    try:
        async for chunk in client.chat_stream(
            messages=messages,
            model="deepseek-v4-flash",
            temperature=0.3,
            max_tokens=800
        ):
            chunks.append(chunk)
        
        chat_duration = time.time() - start_time
        full_text = "".join(chunks)
        
        print(f"✅ 生成成功")
        print(f"⏱️  耗时: {chat_duration:.2f}秒")
        print(f"📝 内容长度: {len(full_text)}字符")
        print(f"\n内容预览:")
        print(full_text[:200] + "...")
        
    except Exception as e:
        print(f"❌ 失败: {e}")
        chat_duration = time.time() - start_time
    
    # 测试流式reasoner
    print("\n" + "-"*80)
    print("\n[测试2] deepseek-v4-flash 流式生成")
    print("-"*80)
    
    start_time = time.time()
    chunks = []
    try:
        async for chunk in client.chat_stream(
            messages=messages,
            model="deepseek-v4-flash",
            temperature=0.3,
            max_tokens=800
        ):
            chunks.append(chunk)
        
        reasoner_duration = time.time() - start_time
        full_text = "".join(chunks)
        
        print(f"✅ 生成成功")
        print(f"⏱️  耗时: {reasoner_duration:.2f}秒")
        print(f"📝 内容长度: {len(full_text)}字符")
        print(f"\n内容预览:")
        print(full_text[:200] + "...")
        
    except Exception as e:
        print(f"❌ 失败: {e}")
        reasoner_duration = time.time() - start_time
    
    print("\n" + "="*80)
    print(f"流式生成耗时对比: chat={chat_duration:.2f}s vs reasoner={reasoner_duration:.2f}s")
    print("="*80)


async def main():
    print("\n🚀 启动DeepSeek模型对比测试...")
    
    # 测试1: 非流式对比
    await test_model_comparison()
    
    # 测试2: 流式对比
    print("\n\n")
    response = input("是否测试流式生成对比? (y/n): ")
    if response.lower() == 'y':
        await test_streaming_comparison()
    
    print("\n✅ 测试完成！")


if __name__ == "__main__":
    asyncio.run(main())
