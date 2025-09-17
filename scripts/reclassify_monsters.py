#!/usr/bin/env python3
"""
怪物类型重构脚本
按照12类精细化分类方案重新分类所有宠物
"""
import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from server.app.db import SessionLocal
from server.app.models import Monster
from sqlalchemy import func

def reclassify_monsters():
    """重新分类所有宠物"""
    
    print("🚀 开始重新分类宠物...")
    
    with SessionLocal() as session:
        # 获取所有宠物
        all_monsters = session.query(Monster).all()
        total_count = len(all_monsters)
        print(f"📊 总计 {total_count} 个宠物需要重新分类")
        
        # 分类统计
        classification_stats = {
            '无双宠物': 0,
            '神宠': 0,
            '珍宠': 0,
            '罗盘宠物': 0,
            'BOSS宠物': 0,
            '可捕捉宠物': 0,
            'VIP宠物': 0,
            '商城宠物': 0,
            '任务宠物': 0,
            '超进化宠物': 0,
            '活动宠物': 0,
            '其他宠物': 0
        }
        
        updated_count = 0
        
        for monster in all_monsters:
            old_type = monster.type
            new_type = classify_monster(monster.method)
            
            if old_type != new_type:
                monster.type = new_type
                updated_count += 1
                print(f"  📝 ID{monster.id} {monster.name}: {old_type} -> {new_type}")
            
            classification_stats[new_type] += 1
        
        # 提交更改
        session.commit()
        
        print(f"\n✅ 重新分类完成!")
        print(f"📈 更新了 {updated_count}/{total_count} 个宠物的分类")
        
        print("\n📊 新分类统计:")
        for category, count in classification_stats.items():
            percentage = (count / total_count) * 100
            print(f"  {category}: {count}个 ({percentage:.1f}%)")

def classify_monster(method):
    """
    根据获取方式分类宠物
    按优先级顺序进行匹配
    """
    if not method:
        return '其他宠物'
    
    method_str = str(method)
    method_lower = method_str.lower()
    
    # 1. 无双宠物 (最高优先级)
    if '无双印记' in method_str or '无双状态' in method_str:
        return '无双宠物'
    
    # 2. 神宠
    if '神宠之魂' in method_str:
        return '神宠'
    
    # 3. 珍宠
    if '珍宠之魂' in method_str:
        return '珍宠'
    
    # 4. 罗盘宠物
    if '寻宝罗盘' in method_str:
        return '罗盘宠物'
    
    # 5. BOSS宠物 (排除商城购买的)
    if (any(keyword in method_str for keyword in ['首次打败', '首次击败', '首次战胜', '首次胜利']) or
        (any(keyword in method_str for keyword in ['击败', '打败', '战胜']) and 
         any(keyword in method_str for keyword in ['可获得', '可以获得', '获得']))) and \
       not any(keyword in method_lower for keyword in ['商城购买', '购买精魄', '炫光商城']):
        return 'BOSS宠物'
    
    # 6. 可捕捉宠物
    if '捕捉' in method_str:
        return '可捕捉宠物'
    
    # 7. VIP宠物
    if any(keyword in method_lower for keyword in ['vip', '年费超级vip']):
        return 'VIP宠物'
    
    # 8. 商城宠物 (购买精魄的)
    if (any(keyword in method_lower for keyword in ['商城购买', '购买精魄', '炫光商城']) and 
        '精魄' in method_str):
        return '商城宠物'
    
    # 9. 任务宠物
    if any(keyword in method_str for keyword in ['卡布召集令', '完成任务', '成就达到', '成就奖励']):
        return '任务宠物'
    
    # 10. 超进化宠物 (排除已匹配的无双)
    if any(keyword in method_str for keyword in ['超进化', '进化']):
        return '超进化宠物'
    
    # 11. 活动宠物
    if '活动' in method_str:
        return '活动宠物'
    
    # 12. 其他宠物
    return '其他宠物'

def verify_classification():
    """验证分类结果"""
    print("\n🔍 验证分类结果...")
    
    with SessionLocal() as session:
        # 统计各类别数量
        type_counts = session.query(
            Monster.type, 
            func.count(Monster.id)
        ).group_by(Monster.type).all()
        
        print("\n📊 验证统计:")
        total = 0
        for type_name, count in type_counts:
            total += count
            print(f"  {type_name}: {count}个")
        
        print(f"\n总计: {total}个")
        
        # 显示每个类别的样本
        print("\n📝 样本检查:")
        for type_name, _ in type_counts:
            samples = session.query(Monster.name, Monster.method).filter(
                Monster.type == type_name
            ).limit(2).all()
            
            print(f"\n{type_name} 样本:")
            for name, method in samples:
                method_short = (method[:60] + '...') if method and len(method) > 60 else method
                print(f"  • {name}: {method_short}")

if __name__ == "__main__":
    try:
        # 执行重新分类
        reclassify_monsters()
        
        # 验证结果
        verify_classification()
        
        print("\n🎉 重构完成！所有宠物已按照12类精细化方案重新分类。")
        
    except Exception as e:
        print(f"❌ 重构失败: {e}")
        raise