import cv2
import numpy as np
import pytesseract
import os
import re
from PIL import Image
from typing import Tuple, Optional, List, Dict
import logging


class ImageRecognizer:
    """图像识别和OCR处理类"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # 设置Tesseract路径
        tesseract_path = os.getenv('TESSERACT_PATH', r'C:\Program Files\Tesseract-OCR\tesseract.exe')
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        
        # 模板匹配阈值
        self.match_threshold = 0.8
        
        # OCR配置
        self.ocr_config = '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789:'
    
    def find_element_by_image(self, screenshot_path: str, template_path: str, 
                             threshold: float = None) -> Optional[Tuple[int, int]]:
        """通过模板匹配查找元素位置
        
        Args:
            screenshot_path: 截图文件路径
            template_path: 模板图片路径
            threshold: 匹配阈值（可选）
            
        Returns:
            Optional[Tuple[int, int]]: 匹配位置 (x, y)，未找到返回None
        """
        if threshold is None:
            threshold = self.match_threshold
        
        try:
            if not os.path.exists(screenshot_path) or not os.path.exists(template_path):
                self.logger.error(f"文件不存在: {screenshot_path} 或 {template_path}")
                return None
            
            # 读取图像
            screenshot = cv2.imread(screenshot_path)
            template = cv2.imread(template_path)
            
            if screenshot is None or template is None:
                self.logger.error("图像读取失败")
                return None
            
            # 模板匹配
            result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val >= threshold:
                # 计算中心点坐标
                h, w = template.shape[:2]
                center_x = max_loc[0] + w // 2
                center_y = max_loc[1] + h // 2
                
                self.logger.info(f"模板匹配成功: {template_path}, 置信度: {max_val:.3f}, 位置: ({center_x}, {center_y})")
                return (center_x, center_y)
            else:
                self.logger.warning(f"模板匹配失败: {template_path}, 最高置信度: {max_val:.3f}")
                return None
                
        except Exception as e:
            self.logger.error(f"模板匹配异常: {e}")
            return None
    
    def find_element_with_label(self, screenshot_path: str, label_template_path: str, 
                               offset_x: int = 150, offset_y: int = 0) -> Optional[Tuple[int, int]]:
        """通过标签定位输入框位置
        
        Args:
            screenshot_path: 截图文件路径
            label_template_path: 标签模板图片路径
            offset_x: 相对标签的X轴偏移
            offset_y: 相对标签的Y轴偏移
            
        Returns:
            Optional[Tuple[int, int]]: 输入框位置 (x, y)，未找到返回None
        """
        try:
            label_pos = self.find_element_by_image(screenshot_path, label_template_path)
            if label_pos:
                input_x = label_pos[0] + offset_x
                input_y = label_pos[1] + offset_y
                self.logger.info(f"通过标签定位输入框: ({input_x}, {input_y})")
                return (input_x, input_y)
            return None
            
        except Exception as e:
            self.logger.error(f"标签定位失败: {e}")
            return None
    
    def extract_text_from_image(self, image_path: str, region: Optional[Tuple[int, int, int, int]] = None,
                               config: str = None) -> str:
        """从图像中提取文本
        
        Args:
            image_path: 图像文件路径
            region: 识别区域 (x, y, width, height)，可选
            config: OCR配置，可选
            
        Returns:
            str: 识别出的文本
        """
        try:
            if not os.path.exists(image_path):
                self.logger.error(f"图像文件不存在: {image_path}")
                return ""
            
            # 读取图像
            image = Image.open(image_path)
            
            # 如果指定了区域，裁剪图像
            if region:
                x, y, w, h = region
                image = image.crop((x, y, x + w, y + h))
            
            # OCR识别
            ocr_config = config or self.ocr_config
            text = pytesseract.image_to_string(image, config=ocr_config, lang='eng+chi_sim')
            
            # 清理文本
            text = text.strip()
            self.logger.info(f"OCR识别结果: {text[:50]}...")
            return text
            
        except Exception as e:
            self.logger.error(f"OCR识别失败: {e}")
            return ""
    
    def get_remaining_time(self, screenshot_path: str) -> Optional[str]:
        """从截图中识别剩余工作时间
        
        Args:
            screenshot_path: 截图文件路径
            
        Returns:
            Optional[str]: 剩余时间字符串，识别失败返回None
        """
        try:
            # 尝试多种OCR配置
            configs = [
                '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789:',
                '--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789:',
                '--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789:',
            ]
            
            for config in configs:
                text = self.extract_text_from_image(screenshot_path, config=config)
                
                # 查找时间格式 (HH:MM:SS 或 HH:MM)
                time_pattern = r'(\d{1,2}:\d{2}(?::\d{2})?)'
                matches = re.findall(time_pattern, text)
                
                if matches:
                    time_str = matches[0]
                    self.logger.info(f"识别到剩余时间: {time_str}")
                    return time_str
            
            self.logger.warning("未能识别剩余时间")
            return None
            
        except Exception as e:
            self.logger.error(f"剩余时间识别失败: {e}")
            return None
    
    def get_punch_records_from_page(self, screenshot_path: str) -> List[Dict[str, str]]:
        """从页面截图中识别打卡记录
        
        Args:
            screenshot_path: 截图文件路径
            
        Returns:
            List[Dict[str, str]]: 打卡记录列表
        """
        try:
            records = []
            
            # 使用OCR识别整个页面
            text = self.extract_text_from_image(screenshot_path, 
                                              config='--oem 3 --psm 6 -l chi_sim+eng')
            
            if not text:
                return records
            
            # 分析文本，提取打卡记录
            lines = text.split('\n')
            current_record = {}
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 查找日期模式
                date_pattern = r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})'
                date_match = re.search(date_pattern, line)
                if date_match:
                    if current_record:
                        records.append(current_record)
                    current_record = {'date': date_match.group(1)}
                
                # 查找时间模式
                time_pattern = r'(\d{1,2}:\d{2}(?::\d{2})?)'
                time_matches = re.findall(time_pattern, line)
                
                if time_matches and current_record:
                    if '上班' in line or '签到' in line:
                        current_record['punch_in'] = time_matches[0]
                    elif '下班' in line or '签退' in line:
                        current_record['punch_out'] = time_matches[0]
            
            # 添加最后一条记录
            if current_record:
                records.append(current_record)
            
            self.logger.info(f"识别到 {len(records)} 条打卡记录")
            return records
            
        except Exception as e:
            self.logger.error(f"打卡记录识别失败: {e}")
            return []
    
    def find_multiple_elements(self, screenshot_path: str, template_paths: List[str],
                              threshold: float = None) -> Dict[str, Optional[Tuple[int, int]]]:
        """查找多个模板元素
        
        Args:
            screenshot_path: 截图文件路径
            template_paths: 模板图片路径列表
            threshold: 匹配阈值（可选）
            
        Returns:
            Dict[str, Optional[Tuple[int, int]]]: 模板名称到位置的映射
        """
        results = {}
        
        for template_path in template_paths:
            template_name = os.path.basename(template_path)
            position = self.find_element_by_image(screenshot_path, template_path, threshold)
            results[template_name] = position
            
        return results
    
    def enhance_image_for_ocr(self, image_path: str, output_path: str = None) -> str:
        """增强图像以提高OCR识别率
        
        Args:
            image_path: 输入图像路径
            output_path: 输出图像路径（可选）
            
        Returns:
            str: 增强后的图像路径
        """
        try:
            # 读取图像
            image = cv2.imread(image_path)
            if image is None:
                return image_path
            
            # 转换为灰度图
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # 应用高斯模糊减少噪声
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            
            # 应用自适应阈值
            thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                         cv2.THRESH_BINARY, 11, 2)
            
            # 形态学操作去除噪声
            kernel = np.ones((2, 2), np.uint8)
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            # 保存增强后的图像
            if output_path is None:
                base, ext = os.path.splitext(image_path)
                output_path = f"{base}_enhanced{ext}"
            
            cv2.imwrite(output_path, cleaned)
            self.logger.info(f"图像增强完成: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"图像增强失败: {e}")
            return image_path
    
    def verify_element_exists(self, screenshot_path: str, template_paths: List[str],
                             min_matches: int = 1) -> bool:
        """验证页面元素是否存在
        
        Args:
            screenshot_path: 截图文件路径
            template_paths: 模板图片路径列表
            min_matches: 最少匹配数量
            
        Returns:
            bool: 元素存在返回True
        """
        try:
            results = self.find_multiple_elements(screenshot_path, template_paths)
            found_count = sum(1 for pos in results.values() if pos is not None)
            
            success = found_count >= min_matches
            self.logger.info(f"元素验证: 找到 {found_count}/{len(template_paths)} 个元素, 需要 {min_matches} 个")
            return success
            
        except Exception as e:
            self.logger.error(f"元素验证失败: {e}")
            return False


# 全局图像识别器实例
image_recognizer = ImageRecognizer()