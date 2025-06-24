#!/usr/bin/env python3
"""
邮件服务测试脚本
用于验证重构后的邮件功能是否正常工作
"""

import os
import time
import logging
from dotenv import load_dotenv
from email_service import EmailService

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_email_service():
    """测试邮件服务功能"""
    print("=== 邮件服务测试 ===")
    
    # 创建邮件服务实例
    email_service = EmailService()
    
    # 1. 测试邮件配置检查
    print("\n1. 检查邮件配置...")
    if not email_service.email_sender or not email_service.email_password:
        print("❌ 邮件配置不完整，请在.env文件中设置以下变量：")
        print("   EMAIL_SENDER=your-email@example.com")
        print("   EMAIL_PASSWORD=your-email-password")
        print("   EMAIL_SMTP_SERVER=smtp.example.com")
        print("   EMAIL_SMTP_PORT=587")
        return False
    else:
        print(f"✅ 邮件配置完整")
        print(f"   发件人: {email_service.email_sender}")
        print(f"   SMTP服务器: {email_service.email_smtp_server}:{email_service.email_smtp_port}")
        print(f"   收件人: {email_service.email_recipients}")
    
    # 2. 测试邮件服务器连接
    print("\n2. 测试邮件服务器连接...")
    if email_service.check_email_connection():
        print("✅ 邮件服务器连接成功")
    else:
        print("❌ 邮件服务器连接失败")
        return False
    
    # 3. 测试同步邮件发送
    print("\n3. 测试同步邮件发送...")
    test_subject = "测试邮件 - 同步发送"
    test_body = f"这是一封测试邮件，发送时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
    
    if email_service.send_email_with_retry(test_subject, test_body):
        print("✅ 同步邮件发送成功")
    else:
        print("❌ 同步邮件发送失败")
        return False
    
    # 4. 测试异步邮件发送
    print("\n4. 测试异步邮件发送...")
    async_subject = "测试邮件 - 异步发送"
    async_body = f"这是一封异步测试邮件，发送时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"
    
    def async_callback(success, subject):
        if success:
            print(f"✅ 异步邮件发送成功: {subject}")
        else:
            print(f"❌ 异步邮件发送失败: {subject}")
    
    email_service.send_email_async(async_subject, async_body, callback=async_callback)
    print("✅ 异步邮件已提交发送队列")
    
    # 5. 测试打卡通知邮件
    print("\n5. 测试打卡通知邮件...")
    email_service.send_punch_notification(
        punch_type="上班",
        success=True,
        message="测试打卡成功",
        user_name="测试用户",
        async_send=False
    )
    print("✅ 打卡通知邮件发送完成")
    
    # 6. 测试系统错误通知邮件
    print("\n6. 测试系统错误通知邮件...")
    email_service.send_system_error_notification(
        error_type="测试错误",
        error_message="这是一个测试错误消息",
        user_name="测试用户",
        async_send=False
    )
    print("✅ 系统错误通知邮件发送完成")
    
    print("\n=== 所有测试完成 ===")
    print("请检查您的邮箱是否收到了测试邮件")
    
    # 等待异步邮件发送完成
    print("\n等待异步邮件发送完成...")
    time.sleep(5)
    
    return True

def test_email_retry_mechanism():
    """测试邮件重试机制"""
    print("\n=== 测试邮件重试机制 ===")
    
    # 创建一个配置错误的邮件服务实例
    email_service = EmailService()
    original_password = email_service.email_password
    
    # 故意设置错误的密码来测试重试
    email_service.email_password = "wrong_password"
    
    print("使用错误密码测试重试机制...")
    success = email_service.send_email_with_retry(
        "重试测试邮件",
        "这封邮件应该发送失败并触发重试机制"
    )
    
    if not success:
        print("✅ 重试机制工作正常，错误密码导致发送失败")
    else:
        print("❌ 重试机制可能有问题，错误密码居然发送成功了")
    
    # 恢复正确的密码
    email_service.email_password = original_password
    
    return True

if __name__ == "__main__":
    try:
        # 运行邮件服务测试
        if test_email_service():
            # 运行重试机制测试
            test_email_retry_mechanism()
            print("\n🎉 所有测试完成！")
        else:
            print("\n❌ 测试失败，请检查配置")
            
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试过程中发生异常: {e}")
        import traceback
        traceback.print_exc()