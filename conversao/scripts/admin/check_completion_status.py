#!/usr/bin/env python3
"""
检查Group 1中哪些PDF已完成,哪些待处理
"""

import os
from pathlib import Path

# 目录
input_dir = Path("combined_input_group1")
results_dir = Path("chunk_results")

# 获取所有输入PDF
input_pdfs = sorted([f.stem for f in input_dir.glob("*.pdf")])

# 检查完成状态
completed = []
pending = []

for pdf_name in input_pdfs:
    result_path = results_dir / pdf_name
    if result_path.exists() and result_path.is_dir():
        completed.append(pdf_name)
    else:
        pending.append(pdf_name)

# 输出统计
print(f"========== Group 1 完成状态 ==========\n")
print(f"总PDF数: {len(input_pdfs)}")
print(f"已完成: {len(completed)}")
print(f"待处理: {len(pending)}")
print(f"完成率: {len(completed)/len(input_pdfs)*100:.1f}%\n")

# 输出待处理列表
print(f"========== 待处理PDF列表 ({len(pending)}个) ==========")
for i, pdf in enumerate(pending, 1):
    print(f"{i:3d}. {pdf}")

# 保存待处理列表到文件
with open("pending_pdfs_group1.txt", "w") as f:
    for pdf in pending:
        f.write(f"{pdf}\n")

print(f"\n✅ 待处理列表已保存到: pending_pdfs_group1.txt")
