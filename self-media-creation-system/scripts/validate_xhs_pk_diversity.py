#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_xhs_pk_diversity.py: 小红书 1+3 PK 候选集发车前特征距离与拓扑正交校验器

架构原则:
1. 核心变量单一锁死: 4 张候选应围绕完全一致的核心事实与指标量级，
   严禁将不同核心变量与不同构图混杂，杜绝 A/B 测试实验归因混淆；
2. 四象限正交拓扑骨架 (Orthogonal Layout Archetypes):
   - Slot 0 [portrait_hero]: 人物半身主视觉 + 左侧大字标题 (主打人格信任)
   - Slot 1 [ui_split_card]: 纯结构化对比卡片与双栏数据条 (主打数字反差)
   - Slot 2 [evidence_macro]: 15° 倾斜文档特写 + 局部高亮标注 (主打一手凭证感)
   - Slot 3 [typographic_poster]: 纯大字报或极简步骤决策树 (主打信息收藏欲)
3. 空间 Sobel 梯度签名 L1 距离门禁:
   - 4x4 分块计算边缘能量分布向量 g_i in Delta^15；
   - 强制任意两图 min L1 >= 0.40 (杜绝仅翻深浅色导致的拓扑同构假差异)；
4. 深度拷贝特征余弦相似度上界 (cos_sim <= 0.68)；
5. 计算 Gram 矩阵行列式 det(G) 作为全局行列式点过程 (DPP) 多样性体积打分。

可选依赖: opencv-python, numpy, Pillow。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

VALID_ARCHETYPES = [
    "portrait_hero",
    "ui_split_card",
    "evidence_macro",
    "typographic_poster"
]


def compute_spatial_gradient_signature(rgb_u8: np.ndarray, grid: int = 4) -> np.ndarray:
    """计算 4x4 空间 Sobel 梯度能量分布签名。"""
    resized = cv2.resize(rgb_u8, (320, 320))
    gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)

    cell_h = 320 // grid
    cell_w = 320 // grid
    cells = []
    for r in range(grid):
        for c in range(grid):
            cell_mag = mag[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w]
            cells.append(float(np.sum(cell_mag)))

    cells_np = np.array(cells, dtype=np.float32)
    total = np.sum(cells_np)
    if total > 1e-6:
        cells_np /= total
    return cells_np


def validate_xhs_pk_quartet(
    images_rgb: list[np.ndarray],
    archetypes: list[str] | None = None,
    min_grid_l1: float = 0.40,
    max_cos_sim: float = 0.68
) -> dict[str, Any]:
    """校验 1+3 四张候选的视觉与空间正交性。"""
    n = len(images_rgb)
    if n != 4:
        raise ValueError(f"小红书 PK 候选集必须恰好包含 4 张图片 (当前 {n} 张)")

    if archetypes is not None:
        if len(archetypes) != 4:
            raise ValueError(f"必须为 4 张候选指定构图骨架 (当前 {len(archetypes)})")
        if len(set(archetypes)) != 4:
            raise ValueError(f"4 张候选的构图骨架必须互不相同，严禁同构 (当前: {archetypes})")

    # 1. 计算 4x4 空间梯度签名
    sigs = [compute_spatial_gradient_signature(im) for im in images_rgb]

    # 2. 计算归一化视觉特征向量 (在无重型深度模型环境，采用多尺度空间颜色矩与边缘直方图拼接近似)
    # 保证零网络环境也能确定性执行
    features = []
    for im in images_rgb:
        im_small = cv2.resize(im, (128, 128))
        hsv = cv2.cvtColor(im_small, cv2.COLOR_RGB2HSV)
        hist_h = cv2.calcHist([hsv], [0], None, [16], [0, 180]).flatten()
        hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256]).flatten()
        hist_v = cv2.calcHist([hsv], [2], None, [8], [0, 256]).flatten()
        grad_sig = compute_spatial_gradient_signature(im, grid=4)
        feat = np.concatenate([hist_h, hist_s, hist_v, grad_sig * 10.0])
        norm = np.linalg.norm(feat)
        if norm > 1e-6:
            feat /= norm
        features.append(feat)

    features_mat = np.array(features)
    cos_matrix = features_mat @ features_mat.T

    # 3. 两两比对
    violations = []
    max_pair_cos = 0.0
    min_pair_l1 = 2.0
    pair_reports = []

    slot_names = [f"Slot_{i}" + (f"({archetypes[i]})" if archetypes else "") for i in range(4)]

    for i in range(4):
        for j in range(i + 1, 4):
            cos_ij = float(cos_matrix[i, j])
            l1_ij = float(np.abs(sigs[i] - sigs[j]).sum())
            max_pair_cos = max(max_pair_cos, cos_ij)
            min_pair_l1 = min(min_pair_l1, l1_ij)

            pair_reports.append({
                "pair": f"{slot_names[i]} vs {slot_names[j]}",
                "cos_sim": round(cos_ij, 3),
                "spatial_l1": round(l1_ij, 3)
            })

            if cos_ij > max_cos_sim:
                violations.append(f"{slot_names[i]} 与 {slot_names[j]} 特征余弦相似度过高 ({cos_ij:.3f} > {max_cos_sim})，存在平台拷贝折叠风险")
            if l1_ij < min_grid_l1:
                violations.append(f"{slot_names[i]} 与 {slot_names[j]} 空间梯度 L1 距离过低 ({l1_ij:.3f} < {min_grid_l1})，画面拓扑高度同构")

    # 计算 Gram 矩阵行列式 (DPP 多样性体积)
    dpp_volume = float(np.linalg.det(cos_matrix))

    passed = (len(violations) == 0)

    return {
        "passed": passed,
        "status": "PASS" if passed else "PK_VARIANCE_COLLAPSE",
        "archetypes": archetypes,
        "max_pairwise_cos": round(max_pair_cos, 3),
        "min_spatial_l1": round(min_pair_l1, 3),
        "dpp_diversity_volume": round(max(0.0, dpp_volume), 4),
        "pair_matrix": pair_reports,
        "violations": violations
    }


def main():
    parser = argparse.ArgumentParser(description="小红书 1+3 PK 候选集特征距离与正交拓扑校验器")
    parser.add_argument("images", nargs=4, help="4 张候选图片路径 (Slot 0 ~ 3)")
    parser.add_argument("--archetypes", nargs=4, default=VALID_ARCHETYPES, help="4 张候选指定的构图骨架")
    parser.add_argument("--json", action="store_true", help="打印 JSON 结构化验收清单")

    args = parser.parse_args()

    loaded = []
    for p in args.images:
        path = Path(p)
        if not path.exists():
            print(f"Error: 找不到图片 {p}", file=sys.stderr)
            sys.exit(1)
        im = Image.open(path).convert("RGB")
        loaded.append(np.array(im))

    res = validate_xhs_pk_quartet(loaded, archetypes=args.archetypes)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"小红书 1+3 PK 多样性校验结果: [{res['status']}]")
        print(f"最大余弦相似度: {res['max_pairwise_cos']} (上限: 0.68) | 最小空间拓扑距离: {res['min_spatial_l1']} (下限: 0.40)")
        print(f"DPP 特征张成体积: {res['dpp_diversity_volume']}")
        if res["violations"]:
            print("\n违规报警项:")
            for v in res["violations"]:
                print(f" - {v}")


if __name__ == "__main__":
    main()
