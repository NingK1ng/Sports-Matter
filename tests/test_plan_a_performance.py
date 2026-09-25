"""
方案A性能测试
验证优化后的响应时间和LLM调用次数
"""
import asyncio
import time
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_single_request():
    """测试单个请求的性能"""
    import aiohttp
    
    url = "http://localhost:8000/api/v1/assistant/chat-stream"
    params = {
        "query": "HIIT训练对心血管健康的影响",
        "use_agent": False,
        "sports_gate": False,
        "top_k": 10,
        "lang": "zh"
    }
    
    print("\n" + "="*60)
    print("📊 方案A性能测试")
    print("="*60)
    print(f"查询: {params['query']}")
    print(f"模式: {'Agent' if params['use_agent'] else '本地检索'}")
    print("-"*60)
    
    start_time = time.time()
    first_token_time = None
    token_count = 0
    search_duration = None
    citations_count = 0
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    print(f"❌ 请求失败: HTTP {response.status}")
                    return
                
                print(f"✅ 连接成功")
                
                async for line in response.content:
                    line_str = line.decode('utf-8').strip()
                    
                    if not line_str or not line_str.startswith('data: '):
                        continue
                    
                    try:
                        import json
                        data = json.loads(line_str[6:])  # 移除 "data: " 前缀
                        event_type = data.get('type')
                        
                        if event_type == 'status':
                            text = data.get('text', '')
                            if '检索完成' in text or '召回' in text:
                                search_duration = time.time() - start_time
                                print(f"\n⏱️  检索阶段: {search_duration:.2f}秒")
                            print(f"📌 {text}")
                        
                        elif event_type == 'token':
                            if first_token_time is None:
                                first_token_time = time.time() - start_time
                                print(f"\n⚡ 首字延迟: {first_token_time:.2f}秒")
                                print("\n💬 生成内容:")
                                print("-" * 60)
                            
                            token_count += 1
                            text = data.get('text', '')
                            print(text, end='', flush=True)
                        
                        elif event_type == 'citations':
                            items = data.get('items', [])
                            citations_count = len(items)
                            print(f"\n\n📚 引用文献: {citations_count}篇")
                            for cite in items[:3]:  # 只显示前3个
                                print(f"  [{cite['idx']}] {cite['title'][:60]}...")
                            if len(items) > 3:
                                print(f"  ... 还有{len(items)-3}篇")
                        
                        elif event_type == 'done':
                            total_time = time.time() - start_time
                            print("\n" + "-" * 60)
                            print("\n✅ 生成完成")
                            print(f"\n📊 性能指标:")
                            print(f"  • 总耗时: {total_time:.2f}秒")
                            if search_duration:
                                print(f"  • 检索耗时: {search_duration:.2f}秒")
                            if first_token_time:
                                print(f"  • 首字延迟: {first_token_time:.2f}秒")
                                print(f"  • 生成耗时: {total_time - first_token_time:.2f}秒")
                            print(f"  • Token数: {token_count}")
                            print(f"  • 引用数: {citations_count}")
                            
                            # 性能评估
                            print(f"\n🎯 性能评估:")
                            if first_token_time and first_token_time < 10:
                                print(f"  ✅ 首字延迟优秀 (<10秒)")
                            elif first_token_time and first_token_time < 30:
                                print(f"  ⚠️  首字延迟一般 (10-30秒)")
                            elif first_token_time:
                                print(f"  ❌ 首字延迟较慢 (>30秒)")
                            
                            if total_time < 180:
                                print(f"  ✅ 总耗时优秀 (<3分钟)")
                            elif total_time < 300:
                                print(f"  ⚠️  总耗时一般 (3-5分钟)")
                            else:
                                print(f"  ❌ 总耗时较慢 (>5分钟)")
                            
                            break
                        
                        elif event_type == 'error':
                            print(f"\n❌ 错误: {data.get('message')}")
                            print(f"   错误码: {data.get('code')}")
                            break
                    
                    except json.JSONDecodeError:
                        continue
    
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


async def test_multiple_queries():
    """测试多个不同查询"""
    queries = [
        "运动后如何恢复",
        "力量训练的好处",
        "预防运动损伤的方法",
    ]
    
    print("\n" + "="*60)
    print("📊 多查询测试")
    print("="*60)
    
    results = []
    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] 测试: {query}")
        print("-"*60)
        
        start_time = time.time()
        first_token_time = None
        
        try:
            import aiohttp
            url = "http://localhost:8000/api/v1/assistant/chat-stream"
            params = {
                "query": query,
                "use_agent": False,
                "top_k": 10,
                "lang": "zh"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    async for line in response.content:
                        line_str = line.decode('utf-8').strip()
                        if not line_str or not line_str.startswith('data: '):
                            continue
                        
                        try:
                            import json
                            data = json.loads(line_str[6:])
                            
                            if data.get('type') == 'token' and first_token_time is None:
                                first_token_time = time.time() - start_time
                                print(f"  ⚡ 首字延迟: {first_token_time:.2f}秒")
                            
                            elif data.get('type') == 'done':
                                total_time = time.time() - start_time
                                print(f"  ✅ 总耗时: {total_time:.2f}秒")
                                results.append({
                                    'query': query,
                                    'first_token': first_token_time,
                                    'total': total_time
                                })
                                break
                        except:
                            continue
        
        except Exception as e:
            print(f"  ❌ 失败: {e}")
        
        await asyncio.sleep(1)  # 间隔1秒
    
    # 统计
    if results:
        print("\n" + "="*60)
        print("📊 统计结果")
        print("="*60)
        avg_first = sum(r['first_token'] for r in results if r['first_token']) / len(results)
        avg_total = sum(r['total'] for r in results) / len(results)
        print(f"平均首字延迟: {avg_first:.2f}秒")
        print(f"平均总耗时: {avg_total:.2f}秒")


async def main():
    """主测试函数"""
    print("\n🚀 启动方案A性能测试...")
    print("⚠️  请确保后端服务已启动 (http://localhost:8000)")
    
    # 等待用户确认
    input("\n按Enter开始测试...")
    
    # 测试1: 单个请求详细测试
    await test_single_request()
    
    # 测试2: 多个查询快速测试
    print("\n\n是否进行多查询测试? (y/n): ", end='')
    if input().lower() == 'y':
        await test_multiple_queries()
    
    print("\n" + "="*60)
    print("✅ 测试完成")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
