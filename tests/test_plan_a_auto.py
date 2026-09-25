"""
方案A自动化性能测试（无需交互）
"""
import asyncio
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_performance():
    """自动化性能测试"""
    import aiohttp
    
    url = "http://localhost:8000/api/v1/assistant/chat-stream"
    params = {
        "query": "HIIT训练对心血管健康的影响",  # 中文查询测试
        "use_agent": "false",  # 转为字符串
        "sports_gate": "false",  # 转为字符串
        "top_k": "10",
        "lang": "zh"
    }
    
    print("\n" + "="*70)
    print("🚀 方案A性能测试 - 自动化运行")
    print("="*70)
    print("\n优化内容：")
    print("  ✅ 移除查询翻译（节省30-60秒）")
    print("  ✅ 移除LLM重排序（节省2-4分钟）")
    print("  ✅ 并行数据库查询（节省2-5秒）")
    print("  ✅ 真流式输出（首字延迟从15分钟降至2-5秒）")
    print("\n" + "-"*70)
    print(f"📝 测试查询: {params['query']}")
    print(f"🔧 模式: 本地检索 (use_agent=False)")
    print("-"*70 + "\n")
    
    start_time = time.time()
    first_token_time = None
    token_count = 0
    search_duration = None
    citations_count = 0
    status_messages = []
    
    try:
        timeout = aiohttp.ClientTimeout(total=600)  # 10分钟超时
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    print(f"❌ 请求失败: HTTP {response.status}")
                    return False
                
                print("✅ 连接成功，开始接收数据...\n")
                
                async for line in response.content:
                    line_str = line.decode('utf-8').strip()
                    
                    if not line_str or not line_str.startswith('data: '):
                        continue
                    
                    try:
                        import json
                        data = json.loads(line_str[6:])
                        event_type = data.get('type')
                        
                        if event_type == 'status':
                            text = data.get('text', '')
                            status_messages.append(text)
                            
                            if '检索完成' in text or '召回' in text:
                                search_duration = time.time() - start_time
                                print(f"⏱️  检索阶段完成: {search_duration:.2f}秒")
                            
                            print(f"📌 状态: {text}")
                        
                        elif event_type == 'token':
                            if first_token_time is None:
                                first_token_time = time.time() - start_time
                                print(f"\n⚡ 首字延迟: {first_token_time:.2f}秒 ⭐")
                                print("\n" + "="*70)
                                print("💬 生成内容（实时流式）:")
                                print("="*70)
                            
                            token_count += 1
                            text = data.get('text', '')
                            print(text, end='', flush=True)
                        
                        elif event_type == 'citations':
                            items = data.get('items', [])
                            citations_count = len(items)
                            print(f"\n\n{'='*70}")
                            print(f"📚 引用文献: {citations_count}篇")
                            print("="*70)
                            for i, cite in enumerate(items[:5], 1):
                                print(f"[{cite['idx']}] {cite['title'][:65]}...")
                                if i < len(items):
                                    print()
                            if len(items) > 5:
                                print(f"\n... 还有{len(items)-5}篇引用")
                        
                        elif event_type == 'done':
                            total_time = time.time() - start_time
                            
                            print("\n" + "="*70)
                            print("✅ 生成完成!")
                            print("="*70)
                            print(f"\n📊 性能指标:")
                            print(f"  • 总耗时: {total_time:.2f}秒 ({total_time/60:.1f}分钟)")
                            
                            if search_duration:
                                print(f"  • 检索耗时: {search_duration:.2f}秒")
                            
                            if first_token_time:
                                print(f"  • 首字延迟: {first_token_time:.2f}秒 ⭐")
                                gen_time = total_time - first_token_time
                                print(f"  • 生成耗时: {gen_time:.2f}秒")
                            
                            print(f"  • Token数: {token_count}")
                            print(f"  • 引用数: {citations_count}")
                            
                            # 性能评估
                            print(f"\n🎯 性能评估:")
                            
                            if first_token_time:
                                if first_token_time < 5:
                                    print(f"  ✅ 首字延迟优秀: {first_token_time:.2f}秒 (<5秒)")
                                elif first_token_time < 10:
                                    print(f"  ✅ 首字延迟良好: {first_token_time:.2f}秒 (5-10秒)")
                                elif first_token_time < 30:
                                    print(f"  ⚠️  首字延迟一般: {first_token_time:.2f}秒 (10-30秒)")
                                else:
                                    print(f"  ❌ 首字延迟较慢: {first_token_time:.2f}秒 (>30秒)")
                            
                            if total_time < 60:
                                print(f"  ✅ 总耗时优秀: {total_time:.2f}秒 (<1分钟)")
                            elif total_time < 180:
                                print(f"  ✅ 总耗时良好: {total_time:.2f}秒 (1-3分钟)")
                            elif total_time < 300:
                                print(f"  ⚠️  总耗时一般: {total_time:.2f}秒 (3-5分钟)")
                            else:
                                print(f"  ❌ 总耗时较慢: {total_time:.2f}秒 (>5分钟)")
                            
                            # 对比原始性能
                            print(f"\n📈 对比优化前:")
                            print(f"  • 原首字延迟: ~900秒 (15分钟)")
                            print(f"  • 现首字延迟: {first_token_time:.2f}秒")
                            improvement = ((900 - first_token_time) / 900) * 100
                            print(f"  • 改进幅度: {improvement:.1f}% ⬆️")
                            
                            print("\n" + "="*70)
                            return True
                        
                        elif event_type == 'error':
                            print(f"\n\n❌ 错误:")
                            print(f"  代码: {data.get('code')}")
                            print(f"  消息: {data.get('message')}")
                            return False
                    
                    except json.JSONDecodeError as e:
                        # 忽略无法解析的行
                        continue
                    except Exception as e:
                        print(f"\n⚠️  处理事件时出错: {e}")
                        continue
    
    except asyncio.TimeoutError:
        print(f"\n❌ 请求超时 (>10分钟)")
        return False
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("\n" + "="*70)
    print("🧪 方案A优化 - 自动化性能测试")
    print("="*70)
    
    success = await test_performance()
    
    print("\n" + "="*70)
    if success:
        print("✅ 测试成功完成")
    else:
        print("❌ 测试失败")
    print("="*70 + "\n")
    
    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
