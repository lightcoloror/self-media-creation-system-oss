#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_safe_zone_svg.py: 基于归一化坐标动态生成平台 UI 禁区与主体保护 SVG 蒙版

架构优势 (替代预烘焙静态 PNG):
1. 任意分辨率自适应 (1080p, 2K, 4K 原生矢量，零拉伸锯齿);
2. 三态色彩编码:
   - 红色虚线 (#EF4444): Hard Exclusion (UI 遮挡或主页裁切区，核心文字严禁进入)
   - 黄色虚线 (#F59E0B): Device Envelope Warn (细长屏裁切或手势条过渡带，主副标需规避)
   - 蓝色实线 (#3B82F6): Protected Subject (人脸、重要凭证等语义保护区)
3. 契约驱动: 直接由 Cover IR 或 PlatformProfile 的 JSON 归一化坐标驱动。
"""

import argparse
import json
import os
import sys

def generate_svg_overlay(
    width: int,
    height: int,
    exclusions: list[dict],
    face_protections: list[dict] = None,
    platform_name: str = "Platform",
    scene_name: str = "Scene"
) -> str:
    """生成带半透明叠层、虚线框与文字标签的独立 SVG 字符串。"""
    svg_elements = []

    # 1. 绘制 UI 禁区多边形 / 矩形
    for exc in exclusions:
        level = exc.get("level", "hard_block")
        reason = exc.get("reason", "")
        exc_id = exc.get("id", "exclusion")

        if level == "hard_block":
            fill_color = "rgba(239, 68, 68, 0.16)"
            stroke_color = "#EF4444"
            dash_array = "12, 8"
            tag_bg = "#EF4444"
        else:  # device_envelope_warn
            fill_color = "rgba(245, 158, 11, 0.12)"
            stroke_color = "#F59E0B"
            dash_array = "8, 6"
            tag_bg = "#F59E0B"

        if "normalizedRect" in exc:
            nx, ny, nw, nh = exc["normalizedRect"]
            rx, ry, rw, rh = nx * width, ny * height, nw * width, nh * height
            svg_elements.append(
                f'  <rect x="{rx:.1f}" y="{ry:.1f}" width="{rw:.1f}" height="{rh:.1f}" '
                f'fill="{fill_color}" stroke="{stroke_color}" stroke-width="3" stroke-dasharray="{dash_array}" />'
            )
            label_y = ry + 24 if ry + 24 < height else ry - 8
            svg_elements.append(
                f'  <text x="{rx + 12:.1f}" y="{label_y:.1f}" fill="{stroke_color}" font-size="16" '
                f'font-family="sans-serif" font-weight="bold">[{level.upper()}] {exc_id} ({reason[:16]})</text>'
            )
        elif "normalizedPoints" in exc:
            pts_str = " ".join(f"{p[0] * width:.1f},{p[1] * height:.1f}" for p in exc["normalizedPoints"])
            svg_elements.append(
                f'  <polygon points="{pts_str}" fill="{fill_color}" stroke="{stroke_color}" '
                f'stroke-width="3" stroke-dasharray="{dash_array}" />'
            )
        elif "coordinates" in exc and len(exc["coordinates"]) == 4:
            # 兼容旧版绝对像素 [x, y, w, h]
            x, y, w, h = exc["coordinates"]
            svg_elements.append(
                f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill_color}" '
                f'stroke="{stroke_color}" stroke-width="3" stroke-dasharray="{dash_array}" />'
            )

    # 2. 绘制人脸与主体保护区域 (蓝色)
    if face_protections:
        for face in face_protections:
            pts = face.get("points", [])
            f_id = face.get("id", "face")
            if len(pts) >= 3:
                pts_str = " ".join(f"{p[0]},{p[1]}" for p in pts)
                svg_elements.append(
                    f'  <polygon points="{pts_str}" fill="rgba(59, 130, 246, 0.10)" stroke="#3B82F6" '
                    f'stroke-width="2" />'
                )
            elif len(pts) == 4:
                # 矩形对角线简化
                pass
            if pts:
                first_x, first_y = pts[0][0], pts[0][1]
                svg_elements.append(
                    f'  <text x="{first_x + 8:.1f}" y="{first_y + 22:.1f}" fill="#3B82F6" font-size="16" '
                    f'font-family="sans-serif" font-weight="bold">[PROTECTED] {f_id}</text>'
                )

    # 3. 顶部水印与配置版本戳
    svg_elements.append(
        f'  <rect x="16" y="16" width="340" height="36" rx="6" fill="rgba(15, 23, 42, 0.75)" />'
    )
    svg_elements.append(
        f'  <text x="26" y="40" fill="#F8FAFC" font-size="14" font-family="sans-serif">'
        f'平台禁区透视: {platform_name.upper()} ({scene_name})</text>'
    )

    svg_content = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        + "\n".join(svg_elements)
        + "\n</svg>"
    )
    return svg_content

def get_default_platform_overlays(platform_key: str) -> list[dict]:
    """读取真实平台浮层配置 (2026-11-18 用户实机核定，彻底剔除臆想禁区)。"""
    config_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "platform-cover-overlays.v1.json"
    )
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            plat = data.get("platforms", {}).get(platform_key.lower())
            if plat and "overlays" in plat:
                return plat["overlays"]
        except Exception:
            pass

    # 兜底内置真实配置 (与 2026-11-18 用户实测核定一致)
    builtin_overlays = {
        "bilibili": [
            {
                "id": "bottom_stats_and_duration",
                "type": "rect",
                "level": "hard_block",
                "normalizedRect": [0.0, 0.84, 1.0, 0.16],
                "reason": "底部播放量、弹幕数及右下角时长"
            }
        ],
        "xiaohongshu": [
            {
                "id": "top_right_video_triangle_tag",
                "type": "rect",
                "level": "hard_block",
                "normalizedRect": [0.86, 0.02, 0.12, 0.08],
                "reason": "双列封面右上角三角形播放视频标记"
            }
        ],
        "douyin": [
            {
                "id": "top_right_video_triangle_tag",
                "type": "rect",
                "level": "hard_block",
                "normalizedRect": [0.86, 0.02, 0.12, 0.08],
                "reason": "双列封面右上角三角形播放视频标记"
            }
        ],
        "weixin_channels": [
            {
                "id": "chat_share_center_play_icon",
                "type": "rect",
                "level": "hard_block",
                "normalizedRect": [0.38, 0.38, 0.24, 0.24],
                "reason": "微信聊天卡片正中三角形播放标记"
            },
            {
                "id": "chat_share_bottom_left_account_name",
                "type": "rect",
                "level": "hard_block",
                "normalizedRect": [0.03, 0.88, 0.55, 0.09],
                "reason": "微信聊天卡片左下角账号名称"
            }
        ]
    }
    return builtin_overlays.get(platform_key.lower(), [])

def main():
    parser = argparse.ArgumentParser(description="动态平台 UI 禁区 SVG 蒙版生成器 (真实外显浮层)")
    parser.add_argument("--cover-ir", type=str, help="输入的 Cover IR JSON 文件路径")
    parser.add_argument("--platform", type=str, default="bilibili", choices=["bilibili", "xiaohongshu", "douyin", "weixin_channels"], help="指定目标平台")
    parser.add_argument("--width", type=int, default=1080, help="画布宽度")
    parser.add_argument("--height", type=int, default=1920, help="画布高度")
    parser.add_argument("--output", type=str, default="safe_zone_overlay.svg", help="输出的 SVG 文件路径")

    args = parser.parse_args()

    exclusions = []
    face_protections = []
    platform_name = args.platform
    scene_name = "Feed"

    if args.cover_ir and os.path.exists(args.cover_ir):
        with open(args.cover_ir, "r", encoding="utf-8") as f:
            ir_data = json.load(f)
        canvas = ir_data.get("document", {}).get("canvas", {})
        args.width = canvas.get("width", args.width)
        args.height = canvas.get("height", args.height)

        constraints = ir_data.get("constraints", {})
        safe_zone = constraints.get("platformSafeZones", {})
        exclusions = safe_zone.get("exclusions", [])
        face_protections = constraints.get("faceProtection", [])
        platform_name = safe_zone.get("platform", platform_name)
        scene_name = safe_zone.get("scene", scene_name)
    else:
        exclusions = get_default_platform_overlays(platform_name)

    svg_res = generate_svg_overlay(
        args.width, args.height, exclusions, face_protections, platform_name, scene_name
    )

    with open(args.output, "w", encoding="utf-8") as out_f:
        out_f.write(svg_res)

    print(f"动态 SVG 蒙版已生成: {args.output} (尺寸: {args.width}x{args.height})")

if __name__ == "__main__":
    main()
