"""
邮件服务模块

负责所有邮件发送相关功能，包括打卡通知、错误报告等
"""

import smtplib
import ssl
import os
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
from datetime import datetime
from typing import List, Optional
import logging
from modules.config import config


class EmailService:
    """邮件服务类，负责处理所有邮件发送相关功能"""
    
    def __init__(self):
        self.email_sender = config.EMAIL_SENDER
        self.email_password = config.EMAIL_PASSWORD
        self.email_smtp_server = config.EMAIL_SMTP_SERVER
        self.email_smtp_port = config.EMAIL_SMTP_PORT
        
        # 默认收件人列表
        self.email_recipients = config.EMAIL_RECIPIENTS

        # 错误通知收件人列表（第1个和第3个邮箱）
        self.error_recipients = self._get_error_recipients()

        # 重试配置
        self.max_retries = config.MAX_RETRIES
        self.retry_delay = 2  # 重试间隔（秒）
        
        self.logger = logging.getLogger(__name__)

    def _get_error_recipients(self) -> List[str]:
        """获取错误通知收件人列表（第1个和第3个邮箱）

        Returns:
            List[str]: 错误通知收件人列表
        """
        recipients = self.email_recipients
        error_list = []
        if len(recipients) >= 1:
            error_list.append(recipients[0])
        if len(recipients) >= 3:
            error_list.append(recipients[2])
        return error_list

    def check_email_connection(self) -> bool:
        """检查邮件服务器连接
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        if not self.email_sender or not self.email_password:
            self.logger.warning("邮件配置不完整，跳过连接测试")
            return False
        
        try:
            # 尝试SSL连接
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self.email_smtp_server, self.email_smtp_port, 
                                context=context, timeout=10) as server:
                server.login(self.email_sender, self.email_password)
                self.logger.info("邮件服务器连接成功 (SSL)")
                return True
                
        except Exception as ssl_error:
            self.logger.warning(f"SSL连接失败: {ssl_error}")
            
            try:
                # 尝试TLS连接
                with smtplib.SMTP(self.email_smtp_server, 587, timeout=10) as server:
                    server.starttls()
                    server.login(self.email_sender, self.email_password)
                    self.logger.info("邮件服务器连接成功 (TLS)")
                    return True
                    
            except Exception as tls_error:
                self.logger.error(f"TLS连接也失败: {tls_error}")
                return False
    
    def _send_email_sync(self, subject: str, body: str, recipients: List[str], 
                        image_path: Optional[str] = None, is_html: bool = False) -> bool:
        """同步发送邮件的内部方法
        
        Args:
            subject: 邮件主题
            body: 邮件正文
            recipients: 收件人列表
            image_path: 图片附件路径（可选）
            is_html: 是否为HTML格式邮件
            
        Returns:
            bool: 发送成功返回True，失败返回False
        """
        if not self.email_sender or not self.email_password:
            self.logger.warning("邮件配置不完整，无法发送邮件")
            return False
        
        try:
            # 创建邮件消息
            msg = MIMEMultipart()
            msg['From'] = self.email_sender
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            
            # 添加邮件正文
            if is_html:
                msg.attach(MIMEText(body, 'html', 'utf-8'))
            else:
                msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # 添加图片附件
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    img_data = f.read()
                    img = MIMEImage(img_data)
                    img.add_header('Content-Disposition', 
                                 f'attachment; filename={os.path.basename(image_path)}')
                    msg.attach(img)
            
            # 发送邮件
            context = ssl.create_default_context()
            
            # sent 标志：仅在 send_message 成功返回后置 True。
            # 只有 sent=True 时，退出 with 块（quit/close 阶段）抛出的异常才视为发送成功；
            # 若异常发生在建连/SSL握手/login/send_message 之前或之中，sent 仍为 False，必须按失败处理。
            sent = False
            try:
                # 尝试SSL连接
                with smtplib.SMTP_SSL(self.email_smtp_server, self.email_smtp_port,
                                    context=context, timeout=30) as server:
                    server.login(self.email_sender, self.email_password)
                    result = server.send_message(msg)
                    sent = True
                    self.logger.info(f"邮件发送成功 (SSL): {subject}")
                    # 邮件发送成功，忽略连接关闭时的潜在错误
                    return True

            except Exception as ssl_error:
                # 邮件已成功投递，异常仅来自连接关闭阶段（quit/close），视为成功
                if sent:
                    self.logger.info(f"邮件发送成功 (SSL，忽略连接关闭异常): {subject}")
                    return True
                # 真正的发送失败（建连/握手/login/send_message 阶段），尝试TLS
                self.logger.warning(f"SSL发送失败，尝试TLS: {ssl_error}")

                sent = False
                try:
                    # 尝试TLS连接
                    with smtplib.SMTP(self.email_smtp_server, 587, timeout=30) as server:
                        server.starttls()
                        server.login(self.email_sender, self.email_password)
                        result = server.send_message(msg)
                        sent = True
                        self.logger.info(f"邮件发送成功 (TLS): {subject}")
                        return True
                except Exception as tls_error:
                    # 邮件已成功投递，异常仅来自连接关闭阶段，视为成功
                    if sent:
                        self.logger.info(f"邮件发送成功 (TLS，忽略连接关闭异常): {subject}")
                        return True
                    # 真正的发送失败
                    self.logger.error(f"TLS发送也失败: {tls_error}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"邮件发送失败: {e}")
            return False
    
    def send_email_with_retry(self, subject: str, body: str, 
                             recipients: Optional[List[str]] = None,
                             image_path: Optional[str] = None, 
                             is_html: bool = False,
                             send_to_all: bool = False) -> bool:
        """带重试机制的邮件发送
        
        Args:
            subject: 邮件主题
            body: 邮件正文
            recipients: 收件人列表（可选，默认使用配置的收件人）
            image_path: 图片附件路径（可选）
            is_html: 是否为HTML格式邮件
            send_to_all: 是否发送给所有收件人，默认False只发送给第一个收件人
            
        Returns:
            bool: 发送成功返回True，失败返回False
        """
        if recipients is None:
            recipients = self.email_recipients
            
        # 如果不是发送给所有人，则只发送给第一个收件人
        if not send_to_all and recipients:
            recipients = [recipients[0]]
        
        if not recipients:
            self.logger.warning("没有配置收件人，无法发送邮件")
            return False
        
        # 进行重试
        for attempt in range(self.max_retries):
            try:
                if self._send_email_sync(subject, body, recipients, image_path, is_html):
                    return True
                    
                if attempt < self.max_retries - 1:
                    self.logger.info(f"邮件发送失败，{self.retry_delay}秒后进行第{attempt + 2}次重试...")
                    time.sleep(self.retry_delay)
                    
            except Exception as e:
                self.logger.error(f"邮件发送异常 (第{attempt + 1}次尝试): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        self.logger.error(f"邮件发送失败，已重试{self.max_retries}次")
        return False
    
    def send_email_async(self, subject: str, body: str,
                        recipients: Optional[List[str]] = None,
                        image_path: Optional[str] = None,
                        is_html: bool = False,
                        send_to_all: bool = False,
                        callback: Optional[callable] = None,
                        cleanup_path: Optional[str] = None) -> None:
        """异步发送邮件（不阻塞主流程）

        Args:
            subject: 邮件主题
            body: 邮件正文
            recipients: 收件人列表（可选，默认使用配置的收件人）
            image_path: 图片附件路径（可选）
            is_html: 是否为HTML格式邮件
            send_to_all: 是否发送给所有收件人，默认False只发送给第一个收件人
            callback: 发送完成后的回调函数（可选）
            cleanup_path: 发送完成后需删除的临时附件路径（可选）。删除责任由本后台线程承担，
                          避免主流程提前 os.remove 与本线程读取附件竞争导致 WinError 32。
        """
        def send_thread():
            try:
                success = self.send_email_with_retry(subject, body, recipients, image_path, is_html, send_to_all)
                if callback:
                    callback(success, subject)
            except Exception as e:
                self.logger.error(f"异步邮件发送异常: {e}")
                if callback:
                    callback(False, subject)
            finally:
                # 附件读取完成后再删除，从根本上消除主流程提前删除的时序竞态
                if cleanup_path:
                    try:
                        if os.path.exists(cleanup_path):
                            os.remove(cleanup_path)
                    except Exception as e:
                        self.logger.warning(f"清理邮件临时截图失败: {cleanup_path}, {e}")

        thread = threading.Thread(target=send_thread, daemon=True)
        thread.start()
        self.logger.info(f"邮件已提交异步发送队列: {subject}")
    
    def send_punch_notification(self, punch_type: str, success: bool, 
                               message: str, screenshot_path: Optional[str] = None,
                               user_name: str = "系统", async_send: bool = True) -> None:
        """发送打卡通知邮件
        
        Args:
            punch_type: 打卡类型（"上班" 或 "下班"）
            success: 打卡是否成功
            message: 通知消息
            screenshot_path: 截图路径（可选）
            user_name: 用户名
            async_send: 是否异步发送
        """
        status = "成功" if success else "失败"
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        subject = f"【{user_name}】{punch_type}打卡{status} - {current_time}"
        
        # 构建邮件正文
        body = f"""
        <html>
        <body>
            <h3>打卡通知</h3>
            <p><strong>用户:</strong> {user_name}</p>
            <p><strong>类型:</strong> {punch_type}打卡</p>
            <p><strong>状态:</strong> {status}</p>
            <p><strong>时间:</strong> {current_time}</p>
            <p><strong>详情:</strong> {message}</p>
            {'<p><em>请查看附件截图获取更多信息</em></p>' if screenshot_path else ''}
        </body>
        </html>
        """
        
        def email_callback(success: bool, subject: str):
            if success:
                self.logger.info(f"打卡通知邮件发送成功: {subject}")
            else:
                self.logger.error(f"打卡通知邮件发送失败: {subject}")
        
        if async_send:
            self.send_email_async(subject, body, image_path=screenshot_path, 
                                is_html=True, callback=email_callback)
        else:
            success = self.send_email_with_retry(subject, body, 
                                               image_path=screenshot_path, is_html=True)
            email_callback(success, subject)
    
    def send_system_error_notification(self, error_type: str, error_message: str,
                                     screenshot_path: Optional[str] = None,
                                     user_name: str = "系统", async_send: bool = True) -> None:
        """发送系统错误通知邮件
        
        Args:
            error_type: 错误类型
            error_message: 错误消息
            screenshot_path: 截图路径（可选）
            user_name: 用户名
            async_send: 是否异步发送
        """
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        subject = f"【{user_name}】系统错误通知 - {error_type} - {current_time}"
        
        body = f"""
        <html>
        <body>
            <h3>系统错误通知</h3>
            <p><strong>用户:</strong> {user_name}</p>
            <p><strong>错误类型:</strong> {error_type}</p>
            <p><strong>时间:</strong> {current_time}</p>
            <p><strong>错误详情:</strong></p>
            <pre>{error_message}</pre>
            {'<p><em>请查看附件截图获取更多信息</em></p>' if screenshot_path else ''}
        </body>
        </html>
        """
        
        # 使用错误通知专用收件人列表（第1和第3个邮箱）
        if async_send:
            self.send_email_async(subject, body, recipients=self.error_recipients,
                                image_path=screenshot_path, is_html=True, send_to_all=True)
        else:
            self.send_email_with_retry(subject, body, recipients=self.error_recipients,
                                      image_path=screenshot_path, is_html=True, send_to_all=True)


# 全局邮件服务实例
email_service = EmailService()