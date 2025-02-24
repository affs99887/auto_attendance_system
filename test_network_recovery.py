import asyncio
import os
from datetime import datetime
import logging
from telegram import Bot
from dotenv import load_dotenv
import sys
import cv2
import numpy as np

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 加载环境变量
load_dotenv()

async def test_network_recovery():
    """测试网络错误恢复机制"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        logging.error("请确保设置了 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 环境变量")
        return
    
    bot = Bot(token)
    test_image_path = "test_image.png"
    
    try:
        # 创建一个有效的测试图片
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:] = (255, 255, 255)  # 创建一个白色图片
        cv2.putText(img, "Test", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        cv2.imwrite(test_image_path, img)
        
        logging.info("开始网络恢复测试...")
        
        # 测试1：正常发送消息
        logging.info("测试1：正常发送消息")
        await bot.send_message(chat_id=chat_id, text="网络测试开始")
        
        # 测试2：模拟网络断开（通过修改token制造错误）
        logging.info("测试2：模拟网络断开")
        bot._token = "invalid_token"
        try:
            await bot.send_message(chat_id=chat_id, text="这条消息应该发送失败")
        except Exception as e:
            logging.info(f"预期的错误发生: {str(e)}")
        
        # 测试3：恢复网络并重试
        logging.info("测试3：恢复网络并重试")
        bot._token = token
        await bot.send_message(chat_id=chat_id, text="网络已恢复")
        
        # 测试4：发送图片测试
        logging.info("测试4：测试发送图片")
        with open(test_image_path, "rb") as photo:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption="测试图片发送"
            )
        
        # 测试5：模拟间歇性网络问题
        logging.info("测试5：模拟间歇性网络问题")
        for i in range(3):
            try:
                if i % 2 == 0:
                    bot._token = "invalid_token"
                else:
                    bot._token = token
                    
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"间歇性测试 #{i+1}"
                )
            except Exception as e:
                logging.info(f"预期的错误发生在第 {i+1} 次测试: {str(e)}")
            
            await asyncio.sleep(2)
        
        # 恢复正常token
        bot._token = token
        
        # 测试6：最终确认
        logging.info("测试6：最终确认")
        await bot.send_message(
            chat_id=chat_id,
            text="网络测试完成！"
        )
        
    except Exception as e:
        logging.error(f"测试过程中发生错误: {str(e)}")
    finally:
        # 清理测试文件
        if os.path.exists(test_image_path):
            os.remove(test_image_path)

if __name__ == "__main__":
    try:
        asyncio.run(test_network_recovery())
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"测试失败: {str(e)}") 