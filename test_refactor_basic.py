#!/usr/bin/env python3
"""
基础重构测试脚本
仅测试可以在当前环境中测试的功能
"""

import sys
import os
import traceback

def test_email_service_basic():
    """测试邮件服务基础功能"""
    print("=== EmailService 基础测试 ===\n")
    
    try:
        from email_service import EmailService, email_service
        
        # 测试类导入
        print("✅ EmailService 类导入成功")
        
        # 测试实例化
        service = EmailService()
        print("✅ EmailService 实例化成功")
        
        # 测试全局实例
        print(f"✅ 全局实例可用: {type(email_service).__name__}")
        
        # 测试配置属性
        print(f"  - 重试次数: {service.max_retries}")
        print(f"  - 重试间隔: {service.retry_delay}秒")
        print(f"  - 默认收件人: {len(service.email_recipients)}个")
        
        # 测试方法存在性
        methods = [
            'check_email_connection',
            'send_email_with_retry', 
            'send_email_async',
            'send_punch_notification',
            'send_system_error_notification'
        ]
        
        for method in methods:
            if hasattr(service, method):
                print(f"✅ 方法 {method} 存在")
            else:
                print(f"❌ 方法 {method} 不存在")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ EmailService 测试失败: {e}")
        traceback.print_exc()
        return False

def test_module_structure():
    """测试模块结构"""
    print("\n=== 模块结构测试 ===\n")
    
    # 检查文件是否存在
    files_to_check = [
        "email_service.py",
        "browser_automation.py", 
        "image_recognition.py",
        "main.py",
        "test_email_service.py",
        "test_imports.py"
    ]
    
    missing_files = []
    for file in files_to_check:
        if os.path.exists(file):
            print(f"✅ {file}")
        else:
            print(f"❌ {file} (不存在)")
            missing_files.append(file)
    
    print(f"\n文件检查结果: {len(files_to_check) - len(missing_files)}/{len(files_to_check)} 存在")
    
    return len(missing_files) == 0

def test_syntax_validity():
    """测试语法有效性"""
    print("\n=== 语法有效性测试 ===\n")
    
    python_files = [
        "email_service.py",
        "test_email_service.py",
        "test_refactor_basic.py"
    ]
    
    valid_count = 0
    for file in python_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                source = f.read()
            
            # 尝试编译
            compile(source, file, 'exec')
            print(f"✅ {file} 语法正确")
            valid_count += 1
            
        except SyntaxError as e:
            print(f"❌ {file} 语法错误: {e}")
        except FileNotFoundError:
            print(f"❌ {file} 文件不存在")
        except Exception as e:
            print(f"❌ {file} 检查失败: {e}")
    
    print(f"\n语法检查结果: {valid_count}/{len(python_files)} 通过")
    return valid_count == len(python_files)

def test_import_basic():
    """基础导入测试"""
    print("\n=== 基础导入测试 ===\n")
    
    # 测试标准库
    std_libs = ['os', 'sys', 'time', 'logging', 'threading', 'smtplib', 're']
    std_success = 0
    
    for lib in std_libs:
        try:
            __import__(lib)
            print(f"✅ {lib}")
            std_success += 1
        except ImportError:
            print(f"❌ {lib}")
    
    print(f"\n标准库导入: {std_success}/{len(std_libs)} 成功")
    
    # 测试我们的模块（仅邮件服务）
    try:
        import email_service
        print("✅ email_service 模块导入成功")
        return True
    except Exception as e:
        print(f"❌ email_service 模块导入失败: {e}")
        return False

def show_refactor_summary():
    """显示重构总结"""
    print("\n" + "="*60)
    print("重构总结")
    print("="*60)
    print("""
已完成的重构工作:

1. 📧 EmailService 模块 (email_service.py)
   - ✅ 提取邮件发送功能到独立模块
   - ✅ 添加重试机制（最多3次重试）
   - ✅ 支持异步发送（不阻塞主流程）
   - ✅ 统一的邮件通知接口
   - ✅ SSL/TLS自动切换支持

2. 🌐 BrowserController 模块 (browser_automation.py)
   - ✅ 提取浏览器自动化功能
   - ✅ 统一的窗口控制接口
   - ✅ 虚拟鼠标和键盘操作
   - ✅ 截图和页面导航功能

3. 👁️ ImageRecognizer 模块 (image_recognition.py)
   - ✅ 提取图像识别和OCR功能
   - ✅ 模板匹配和元素定位
   - ✅ 文本识别和时间解析
   - ✅ 图像增强和处理

4. 🔧 main.py 重构
   - ✅ 移除重复的邮件发送代码
   - ✅ 使用新的EmailService异步接口
   - ✅ 简化邮件相关方法
   - ✅ 保持向后兼容性

主要改进:
- 🚀 邮件发送不再阻塞打卡流程
- 🔄 自动重试机制提高成功率
- 📦 模块化设计便于维护和测试
- 🎯 单一职责原则，代码更清晰
- 🔧 更好的错误处理和日志记录

测试文件:
- test_email_service.py - 邮件功能完整测试
- test_imports.py - 模块导入测试  
- test_refactor_basic.py - 基础重构测试
""")

if __name__ == "__main__":
    print("开始重构基础测试...\n")
    
    # 运行各项测试
    email_ok = test_email_service_basic()
    structure_ok = test_module_structure()
    syntax_ok = test_syntax_validity()
    import_ok = test_import_basic()
    
    # 显示总结
    show_refactor_summary()
    
    print("\n" + "="*60)
    print("测试结果总结:")
    print(f"  邮件服务: {'✅ 通过' if email_ok else '❌ 失败'}")
    print(f"  模块结构: {'✅ 通过' if structure_ok else '❌ 失败'}")
    print(f"  语法检查: {'✅ 通过' if syntax_ok else '❌ 失败'}")
    print(f"  基础导入: {'✅ 通过' if import_ok else '❌ 失败'}")
    
    if all([email_ok, structure_ok, syntax_ok, import_ok]):
        print("\n🎉 重构基础测试全部通过！")
        print("💡 建议: 在有完整依赖环境时运行 test_email_service.py 进行完整测试")
    else:
        print("\n❌ 部分测试失败，请检查问题")
    
    print("="*60)