"""
一键启动内网穿透脚本

使用 localhost.run 免费隧道，无需注册，无需安装额外软件。
电脑需要保持开机 + Flask 服务运行。

使用方法:
    1. 先启动 Flask 服务:  .venv/Scripts/python app.py
    2. 新开一个终端窗口运行本脚本:  python start_tunnel.py

获取到的公网 URL 可以在任何设备的浏览器中打开。
"""
import subprocess
import sys
import time
import re
import os

def main():
    print("=" * 55)
    print("  内网穿透 - localhost.run 免费隧道")
    print("=" * 55)
    print()
    print("  确保 Flask 服务已在 http://127.0.0.1:5000 运行")
    print("  正在建立隧道...")
    print()

    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-R", "80:localhost:5000",
        "nokey@localhost.run"
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        url_found = False
        for line in proc.stdout:
            print(line, end="")
            # 匹配隧道 URL
            match = re.search(r"https://[a-z0-9]+\.lhr\.life", line)
            if match and not url_found:
                url = match.group(0)
                url_found = True
                print()
                print("=" * 55)
                print(f"  公网地址: {url}")
                print("=" * 55)
                print()
                print("  在任何设备浏览器中打开上面的地址即可访问。")
                print("  按 Ctrl+C 关闭隧道。")
                print()

        proc.wait()

    except KeyboardInterrupt:
        print("\n隧道已关闭。")
        proc.terminate()
    except FileNotFoundError:
        print("\n错误: 未找到 ssh 命令。")
        print("Windows 10/11 自带 OpenSSH，请在「设置 > 应用 > 可选功能」中安装。")
    except Exception as e:
        print(f"\n错误: {e}")


if __name__ == "__main__":
    main()
