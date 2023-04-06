import random

# 生成随机数
random_num = random.randint(0, 100)

# 打开 README.md 文件
with open('README.md', 'a') as f:
    # 写入随机数
    f.write(f'生成的随机数是：{random_num}n')
