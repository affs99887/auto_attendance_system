#!/usr/bin/env python3
"""
简单的GUI测试脚本
用于测试基本的GUI功能，无需所有依赖
"""

def test_basic_gui():
    """测试基本GUI功能"""
    try:
        import tkinter as tk
        print("✅ tkinter 可用")
        
        # 创建测试窗口
        root = tk.Tk()
        root.title("GUI测试")
        root.geometry("400x300")
        
        # 添加标签
        label = tk.Label(root, text="GUI客户端测试成功！\n所有依赖正常", 
                        font=("Arial", 14), fg="green")
        label.pack(expand=True)
        
        # 添加关闭按钮
        button = tk.Button(root, text="关闭", command=root.destroy, 
                          font=("Arial", 12))
        button.pack(pady=10)
        
        print("✅ 基本GUI功能正常")
        print("正在显示测试窗口...")
        
        # 显示窗口
        root.mainloop()
        return True
        
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请安装 python3-tkinter:")
        print("  Ubuntu/Debian: sudo apt-get install python3-tkinter")
        print("  CentOS/RHEL: sudo yum install tkinter")
        print("  或使用: sudo apt install python3-tk")
        return False
    except Exception as e:
        print(f"❌ GUI测试失败: {e}")
        return False

if __name__ == "__main__":
    print("=== GUI客户端基础测试 ===")
    test_basic_gui()