"""生成《即时百分百》推介资料 PDF。

将各套 content.md 渲染为 A4 中文 PDF（含封面图）。
用法: python scripts/generate_promo_pdf.py [set_dir ...]
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from fpdf import FPDF

PROMO_DIR = Path(__file__).resolve().parent.parent / "docs" / "promo"
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

# 各套资料元信息
SETS = {
    "investor": {"title": "《即时百分百》在线服务平台", "subtitle": "投资人版推介", "slogan": "一个平台，承载所有服务"},
    "supplier": {"title": "《即时百分百》在线服务平台", "subtitle": "服务商版推介", "slogan": "让技能变成稳定的收入"},
    "consumer": {"title": "《即时百分百》在线服务平台", "subtitle": "用户版推介", "slogan": "找靠谱服务，上《即时百分百》"},
    "general": {"title": "《即时百分百》在线服务平台", "subtitle": "综合推介", "slogan": "一个平台，承载所有服务"},
    "escort": {"title": "《即时百分百》专业陪驾", "subtitle": "陪驾业务推介", "slogan": "专业陪驾，安全上路"},
    "easy": {"title": "《即时百分百》在线服务平台", "subtitle": "通俗易懂版推介", "slogan": "随叫随到，百分百放心"},
}

BLUE = (22, 119, 255)
ORANGE = (255, 122, 26)
DARK = (50, 50, 50)
GRAY = (120, 120, 120)
LIGHT = (240, 244, 250)


class PromoPDF(FPDF):
    def __init__(self, meta: dict):
        super().__init__()
        self.meta = meta
        self.add_font("zh", "", FONT_PATH)
        self.add_font("zh", "B", FONT_PATH)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(14, 14, 14)

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("zh", "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 6, f"{self.meta['title']} · {self.meta['subtitle']}", align="L")
        self.cell(0, 6, f"第 {self.page_no()} 页", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LIGHT)
        self.line(14, 13, 196, 13)
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("zh", "", 7)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"《即时百分百》在线服务平台 · 生成于 {datetime.now().strftime('%Y-%m-%d')}", align="C")

    # ---------- 封面 ----------
    def cover(self, cover_image: str | None):
        self.add_page()
        if cover_image and Path(cover_image).exists():
            try:
                self.image(cover_image, 14, 22, w=182, h=102)
            except Exception:
                pass
            y = 132
        else:
            y = 70
        self.set_y(y)
        self.set_font("zh", "B", 30)
        self.set_text_color(*BLUE)
        self.cell(0, 16, self.meta["title"], align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)
        self.set_font("zh", "", 16)
        self.set_text_color(*DARK)
        self.cell(0, 10, self.meta["subtitle"], align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(6)
        self.set_draw_color(*ORANGE)
        self.set_line_width(0.8)
        self.line(80, self.get_y(), 130, self.get_y())
        self.set_line_width(0.2)
        self.ln(6)
        self.set_font("zh", "", 13)
        self.set_text_color(*ORANGE)
        self.cell(0, 10, self.meta["slogan"], align="C", new_x="LMARGIN", new_y="NEXT")

    # ---------- 章节 ----------
    def chapter(self, text: str, level: int):
        if level == 1:
            self.add_page()
            self.set_font("zh", "B", 17)
            self.set_text_color(*BLUE)
            self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*BLUE)
            self.set_line_width(0.6)
            self.line(14, self.get_y() + 1, 196, self.get_y() + 1)
            self.set_line_width(0.2)
            self.ln(7)
        elif level == 2:
            self.set_font("zh", "B", 13)
            self.set_text_color(*DARK)
            self.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
            self.ln(2)
        else:
            self.set_font("zh", "B", 11)
            self.set_text_color(*DARK)
            self.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
            self.ln(1)

    def paragraph(self, text: str):
        self.set_font("zh", "", 10.5)
        self.set_text_color(*DARK)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def bullet(self, text: str):
        self.set_font("zh", "", 10.5)
        self.set_text_color(*DARK)
        clean = re.sub(r"^[-*+]\s+", "", text.strip())
        x = self.get_x()
        self.set_x(x + 5)
        self.multi_cell(0, 6, f"•  {clean}")
        self.ln(1)

    def quote(self, text: str):
        self.set_font("zh", "", 10.5)
        self.set_text_color(*GRAY)
        clean = re.sub(r"^>\s?", "", text.strip())
        self.set_fill_color(*LIGHT)
        self.multi_cell(0, 6, clean, fill=True)
        self.ln(2)

    def table(self, rows: list[list[str]]):
        ncols = max(len(r) for r in rows)
        w = 182 / ncols
        self.set_font("zh", "B", 9)
        self.set_fill_color(*BLUE)
        self.set_text_color(255, 255, 255)
        for i, cell in enumerate(rows[0]):
            self.cell(w, 8, cell, border=1, fill=True, align="C")
        self.ln()
        self.set_font("zh", "", 9)
        self.set_text_color(*DARK)
        for row in rows[1:]:
            self.set_fill_color(255, 255, 255)
            for cell in row:
                self.cell(w, 7, cell, border=1)
            self.ln()
        self.ln(3)

    def hr(self):
        self.set_draw_color(*LIGHT)
        self.line(14, self.get_y() + 1, 196, self.get_y() + 1)
        self.ln(5)


def parse_markdown(text: str) -> list[tuple]:
    """解析 Markdown 为块列表: (type, content)。"""
    blocks: list[tuple] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 表格：连续以 | 开头的行
        if stripped.startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = [header]
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(row)
                i += 1
            blocks.append(("table", rows))
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            blocks.append(("heading", (level, m.group(2))))
            i += 1
            continue

        # 分割线
        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            blocks.append(("hr", ""))
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            blocks.append(("quote", stripped))
            i += 1
            continue

        # 列表项
        if re.match(r"^[-*+]\s+", stripped):
            blocks.append(("bullet", stripped))
            i += 1
            continue

        # 有序列表
        if re.match(r"^\d+\.\s+", stripped):
            blocks.append(("bullet", stripped))
            i += 1
            continue

        # 段落（合并后续普通行）
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith("#") or nxt.startswith("|") or \
               re.match(r"^(-{3,}|\*{3,})$", nxt) or nxt.startswith(">"):
                break
            para.append(nxt)
            i += 1
        blocks.append(("paragraph", " ".join(para)))
    return blocks


def generate_pdf(set_name: str) -> Path:
    meta = SETS[set_name]
    set_dir = PROMO_DIR / set_name
    md_path = set_dir / "content.md"
    if not md_path.exists():
        raise FileNotFoundError(f"缺少文案文件: {md_path}")

    cover_image = set_dir / "cover_cn.jpg"
    if not cover_image.exists():
        cover_image = PROMO_DIR / "assets" / "platform_engine_cn.jpg"

    pdf = PromoPDF(meta)
    pdf.cover(str(cover_image))

    blocks = parse_markdown(md_path.read_text(encoding="utf-8"))
    for kind, content in blocks:
        if kind == "heading":
            pdf.chapter(content[1], content[0])
        elif kind == "paragraph":
            pdf.paragraph(content)
        elif kind == "bullet":
            pdf.bullet(content)
        elif kind == "quote":
            pdf.quote(content)
        elif kind == "table":
            pdf.table(content)
        elif kind == "hr":
            pdf.hr()

    out = set_dir / "promo.pdf"
    pdf.output(str(out))
    print(f"[OK] {set_name}: {out}")
    return out


if __name__ == "__main__":
    targets = sys.argv[1:] or list(SETS.keys())
    for name in targets:
        try:
            generate_pdf(name)
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
