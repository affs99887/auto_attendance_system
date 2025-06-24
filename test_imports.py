#!/usr/bin/env python3
"""
模块导入测试脚本
验证重构后的模块是否可以正常导入和初始化
"""

import sys
import traceback

def test_module_imports():
    """测试所有模块的导入"""
    print("=== 模块导入测试 ===\n")
    
    modules_to_test = [
        ("email_service", "EmailService"),
        ("browser_automation", "BrowserController"),
        ("image_recognition", "ImageRecognizer"),
    ]
    
    success_count = 0
    total_count = len(modules_to_test)
    
    for module_name, class_name in modules_to_test:
        try:
            print(f"测试导入 {module_name}.{class_name}...")
            
            # 动态导入模块
            module = __import__(module_name)
            
            # 获取类并尝试实例化
            cls = getattr(module, class_name)
            instance = cls()
            
            print(f"✅ {module_name}.{class_name} 导入和实例化成功")
            success_count += 1
            
        except Exception as e:
            print(f"❌ {module_name}.{class_name} 导入失败: {e}")
            traceback.print_exc()
    
    print(f"\n导入测试结果: {success_count}/{total_count} 成功")
    
    # 测试全局实例
    print("\n=== 全局实例测试 ===\n")
    
    global_instances = [
        ("email_service", "email_service"),
        ("browser_automation", "browser_controller"),
        ("image_recognition", "image_recognizer"),
    ]
    
    global_success = 0
    for module_name, instance_name in global_instances:
        try:
            print(f"测试全局实例 {module_name}.{instance_name}...")
            
            module = __import__(module_name)
            instance = getattr(module, instance_name)
            
            print(f"✅ {module_name}.{instance_name} 全局实例可用")
            global_success += 1
            
        except Exception as e:
            print(f"❌ {module_name}.{instance_name} 全局实例失败: {e}")
    
    print(f"\n全局实例测试结果: {global_success}/{len(global_instances)} 成功")
    
    return success_count == total_count and global_success == len(global_instances)

def test_main_imports():
    """测试main.py的导入"""
    print("\n=== main.py 导入测试 ===\n")
    
    try:
        print("测试 main.py 导入...")
        
        # 尝试导入main模块（这会执行导入但不运行主程序）
        import main
        
        print("✅ main.py 导入成功")
        
        # 检查主要类是否存在
        if hasattr(main, 'TelegramBot'):
            print("✅ TelegramBot 类存在")
        else:
            print("❌ TelegramBot 类不存在")
            
        if hasattr(main, 'AttendanceSystem'):
            print("✅ AttendanceSystem 类存在")
        else:
            print("❌ AttendanceSystem 类不存在")
            
        return True
        
    except Exception as e:
        print(f"❌ main.py 导入失败: {e}")
        traceback.print_exc()
        return False

def test_dependencies():
    """测试依赖项"""
    print("\n=== 依赖项测试 ===\n")
    
    dependencies = [
        "schedule",
        "telegram",
        "dotenv",
        "logging",
        "smtplib",
        "email.mime.multipart",
        "threading",
        "psutil",
        "chinese_calendar",
    ]
    
    success_count = 0
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"✅ {dep}")
            success_count += 1
        except ImportError as e:
            print(f"❌ {dep}: {e}")
    
    print(f"\n依赖项测试结果: {success_count}/{len(dependencies)} 成功")
    return success_count == len(dependencies)

if __name__ == "__main__":
    try:
        print("开始模块重构测试...\n")
        
        # 测试模块导入
        modules_ok = test_module_imports()
        
        # 测试依赖项
        deps_ok = test_dependencies()
        
        # 测试main.py导入
        main_ok = test_main_imports()
        
        print("\n" + "="*50)
        print("测试总结:")
        print(f"  模块导入: {'✅ 通过' if modules_ok else '❌ 失败'}")
        print(f"  依赖项: {'✅ 通过' if deps_ok else '❌ 失败'}")
        print(f"  main.py导入: {'✅ 通过' if main_ok else '❌ 失败'}")
        
        if modules_ok and deps_ok and main_ok:
            print("\n🎉 所有测试通过！重构成功！")
            sys.exit(0)
        else:
            print("\n❌ 部分测试失败，需要修复")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试过程中发生异常: {e}")
        traceback.print_exc()
        sys.exit(1)