import datetime

# 获取当前时间并格式化为字符串
current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 要写入README.md的文本
text_to_write = f"This file was last updated on {current_time}."

# 打开README.md文件，以写入模式打开
with open("README.md", "w") as file:
    file.write(text_to_write)
