#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calculate_visual_overflow.py: 文本与图层视觉外扩 (visualOverflow) 四方向精确计算器

解决核心痛点:
单纯取 max(strokeWidth/2, shadow.blur) 无法保证阴影在 offsetX/offsetY 偏移下的真实物理边界。
本模块依据 3x blur 保守支撑区间与描边/抗锯齿层级，分别计算上、下、左、右四个方向的必要外扩安全垫。
"""

from dataclasses import dataclass
import math
import sys

@dataclass
class VisualOverflowResult:
    left: float
    right: float
    top: float
    bottom: float
    max_padding: float
    details: dict

def calculate_visual_overflow(
    stroke_width: float = 0.0,
    stroke_alignment: str = "center",  # "center" | "outside" | "inside"
    shadow_blur: float = 0.0,
    shadow_offset_x: float = 0.0,
    shadow_offset_y: float = 0.0,
    shadow_spread: float = 0.0,
    antialias_padding: float = 2.0,
    extra_padding: float = 4.0,
    blur_support_factor: float = 2.5   # 实用工程收敛系数: 2.5 ~ 3.0 倍 blur 覆盖 98% 能量分布
) -> VisualOverflowResult:
    """计算描边、投影及滤镜在四个方向上的理论必要外扩像素值。"""

    # 1. 描边外扩测算
    if stroke_alignment == "outside":
        p_stroke = stroke_width
    elif stroke_alignment == "inside":
        p_stroke = 0.0
    else:  # center (默认)
        p_stroke = stroke_width / 2.0

    # 2. 阴影有效支撑范围估算
    effective_blur = shadow_blur * blur_support_factor + shadow_spread

    # 分别计算上下左右四个方向的阴影外扩
    # left: 向左扩展受负 offsetX 强化，正 offsetX 减弱
    p_shadow_left = max(0.0, effective_blur - shadow_offset_x)
    p_shadow_right = max(0.0, effective_blur + shadow_offset_x)
    p_shadow_top = max(0.0, effective_blur - shadow_offset_y)
    p_shadow_bottom = max(0.0, effective_blur + shadow_offset_y)

    # 3. 效果叠加 (描边外扩与阴影支撑范围的并集或叠加)
    # 若阴影作用于描边之后的轮廓，采用加和保守估算
    p_effect_l = p_stroke + p_shadow_left if shadow_blur > 0 else p_stroke
    p_effect_r = p_stroke + p_shadow_right if shadow_blur > 0 else p_stroke
    p_effect_t = p_stroke + p_shadow_top if shadow_blur > 0 else p_stroke
    p_effect_b = p_stroke + p_shadow_bottom if shadow_blur > 0 else p_stroke

    # 4. 加入抗锯齿与额外安全设计留白
    base_extra = antialias_padding + extra_padding
    pad_l = math.ceil(p_effect_l + base_extra)
    pad_r = math.ceil(p_effect_r + base_extra)
    pad_t = math.ceil(p_effect_t + base_extra)
    pad_b = math.ceil(p_effect_b + base_extra)

    max_pad = max(pad_l, pad_r, pad_t, pad_b)

    return VisualOverflowResult(
        left=pad_l,
        right=pad_r,
        top=pad_t,
        bottom=pad_b,
        max_padding=max_pad,
        details={
            "stroke_outward": p_stroke,
            "shadow_effective_blur": effective_blur,
            "shadow_directions": {
                "left": p_shadow_left,
                "right": p_shadow_right,
                "top": p_shadow_top,
                "bottom": p_shadow_bottom
            },
            "antialias_padding": antialias_padding,
            "extra_padding": extra_padding
        }
    )

def test_overflow_cases():
    """验证 5 类典型视觉修饰用例的四方向外扩计算。"""
    print("=" * 68)
    print("运行 calculate_visual_overflow 边界计算测试...")
    print("=" * 68)

    # 案例 1: 纯 4px 描边
    r1 = calculate_visual_overflow(stroke_width=4.0)
    print(f"\n[案例 1] 纯 4px 描边 -> L:{r1.left}px, R:{r1.right}px, T:{r1.top}px, B:{r1.bottom}px (最大 {r1.max_padding}px)")
    assert r1.max_padding >= 8, "4px描边必须至少预留 8px (2px描边 + 2px抗锯齿 + 4px留白)"

    # 案例 2: 纯 16px 外发光 (无偏移)
    r2 = calculate_visual_overflow(shadow_blur=16.0)
    print(f"[案例 2] 纯 16px 外发光 -> 均衡四周 {r2.max_padding}px")
    assert r2.left == r2.right == r2.top == r2.bottom, "无偏移外发光四周应完全对称"

    # 案例 3: 4px 描边 + 16px 阴影 (offsetX=5, offsetY=8)
    r3 = calculate_visual_overflow(stroke_width=4.0, shadow_blur=16.0, shadow_offset_x=5.0, shadow_offset_y=8.0)
    print(f"[案例 3] 描边 + 方向阴影 -> L:{r3.left}px, R:{r3.right}px, T:{r3.top}px, B:{r3.bottom}px")
    assert r3.bottom > r3.top, "向下偏置的阴影其底边外扩必须大于顶边"
    assert r3.right > r3.left, "向右偏置的阴影其右边外扩必须大于左边"

    # 案例 4: 粗 12px 描边 + 24px 阴影
    r4 = calculate_visual_overflow(stroke_width=12.0, shadow_blur=24.0, shadow_offset_y=12.0)
    print(f"[案例 4] 极端粗描边+大投影 -> 底边需预留 {r4.bottom}px (顶边 {r4.top}px)")
    assert r4.bottom > 70, "大投影场景下必须具备动态大安全垫"

    print("\n" + "=" * 68)
    print("所有视觉外扩公式算术验证通过！")
    print("=" * 68)

if __name__ == "__main__":
    test_overflow_cases()
