"""生成《即时百分百》阶段性总结（规划 vs 现状）的 PDF 与长图。

产物（docs/summary/）：
- summary.pdf   由 content.md 渲染为 A4 中文 PDF
- longpage.png  由 longpage.html 用 Edge 无头模式渲染并裁剪为长图
用法: python scripts/generate_phase_summary.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_DIR = ROOT / "docs" / "summary"
MD_PATH = SUMMARY_DIR / "content.md"
HTML_PATH = SUMMARY_DIR / "longpage.html"
PDF_PATH = SUMMARY_DIR / "summary.pdf"
PNG_PATH = SUMMARY_DIR / "longpage.png"
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

BLUE = (22, 119, 255)
ORANGE = (255, 122, 26)
DARK = (50, 50, 50)
GRAY = (120, 120, 120)
LIGHT = (240, 244, 250)


class SummaryPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("zh", "", FONT_PATH)
        self.add_font("zh", "B", FONT_PATH)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(14, 14, 14)

    def header(self):
        if self.page_no() <= 1:
            return
        self.set_font("zh", "", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 6, "《即时百分百》阶段性总结 · 规划 vs 现状", align="L")
        self.cell(0, 6, f"第 {self.page_no()} 页", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LIGHT)
        self.line(14, 13, 196, 13)
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("zh", "", 7)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"《即时百分百》在线服务平台 · 生成于 {datetime.now().strftime('%Y-%m-%d')}", align="C")

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
        self.set_x(self.get_x() + 5)
        self.multi_cell(0, 6, f"•  {clean}")
        self.ln(1)

    def quote(self, text: str):
        self.set_font("zh", "", 10.5)
        self.set_text_color(*GRAY)
        clean = re.sub(r"^>\s?", "", text.strip())
        self.set_fill_color(*LIGHT)
        self.multi_cell(0, 6, clean, fill=True)
        self.ln(2)

    # ---------- 支持换行的表格 ----------
    @staticmethod
    def _wrap(text: str, width: float, measure) -> list[str]:
        lines: list[str] = []
        for para in str(text).split("\n"):
            if not para.strip():
                lines.append("")
                continue
            line = ""
            for ch in para:
                if line and measure(line + ch) > width:
                    lines.append(line.rstrip())
                    line = ch
                else:
                    line += ch
            lines.append(line.rstrip())
        return lines

    def table(self, rows: list[list[str]]):
        ncols = max(len(r) for r in rows)
        w = 182 / ncols
        pad = 1.5
        line_h = 4.4
        fs = 8.5
        self.set_font("zh", "", fs)
        for ri, row in enumerate(rows):
            lines_per_cell = [
                self._wrap(cell, w - 2 * pad, self.get_string_width) for cell in row
            ]
            row_h = max((len(ls) for ls in lines_per_cell), default=1) * line_h + 2 * pad
            if self.get_y() + row_h > 297 - 18:
                self.add_page()
            x0 = self.get_x()
            y0 = self.get_y()
            for ci, cell in enumerate(row):
                x = x0 + ci * w
                self.rect(x, y0, w, row_h)
                if ri == 0:
                    self.set_fill_color(*BLUE)
                    self.rect(x, y0, w, row_h, style="F")
                    self.set_text_color(255, 255, 255)
                    self.set_font("zh", "B", fs)
                else:
                    if ri % 2 == 0:
                        self.set_fill_color(250, 252, 255)
                        self.rect(x, y0, w, row_h, style="F")
                    self.set_text_color(*DARK)
                    self.set_font("zh", "", fs)
                lines = lines_per_cell[ci]
                for li, ln in enumerate(lines):
                    if ln:
                        self.set_xy(x + pad, y0 + pad + li * line_h)
                        self.cell(w - 2 * pad, line_h, ln)
            self.set_xy(x0, y0 + row_h)
        self.ln(3)


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
        if stripped.startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = [header]
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("table", rows))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            blocks.append(("heading", (len(m.group(1)), m.group(2))))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            blocks.append(("hr", ""))
            i += 1
            continue
        if stripped.startswith(">"):
            blocks.append(("quote", stripped))
            i += 1
            continue
        if re.match(r"^[-*+]\s+", stripped):
            blocks.append(("bullet", stripped))
            i += 1
            continue
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


def generate_pdf() -> Path:
    pdf = SummaryPDF()
    # 封面
    pdf.add_page()
    pdf.ln(45)
    pdf.set_font("zh", "B", 26)
    pdf.set_text_color(*BLUE)
    pdf.cell(0, 14, "《即时百分百》阶段性总结", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("zh", "", 15)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 10, "规划 vs 现状 全景对比", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_draw_color(*ORANGE)
    pdf.set_line_width(0.8)
    pdf.line(80, pdf.get_y(), 130, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(8)
    pdf.set_font("zh", "", 11)
    pdf.set_text_color(*GRAY)
    for meta in ["通用市场交易协调引擎 UMCP-Core", "版本 1.0.0", "生成日期: 2026-09-18", "基线 commit: d684ef7"]:
        pdf.cell(0, 8, meta, align="C", new_x="LMARGIN", new_y="NEXT")

    blocks = parse_markdown(MD_PATH.read_text(encoding="utf-8"))
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
            pdf.ln(4)

    pdf.output(str(PDF_PATH))
    print(f"[OK] PDF: {PDF_PATH}")
    return PDF_PATH


def render_longpage() -> Path:
    """用 Edge 无头模式渲染 longpage.html 为长图并裁剪空白。"""
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not Path(edge).exists():
        raise FileNotFoundError("未找到 msedge.exe，无法渲染长图")

    tmp_dir = Path(tempfile.mkdtemp(prefix="umcp_png_"))
    url = HTML_PATH.resolve().as_uri()
    height = 8000
    while height <= 64000:
        shot = tmp_dir / "shot.png"
        cmd = [
            edge, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            f"--user-data-dir={tmp_dir / 'profile'}",
            f"--window-size=880,{height}",
            f"--screenshot={shot}", url,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        img = Image.open(shot).convert("RGB")
        bbox = img.getbbox()  # 非纯黑区域；长图为白底
        # 以非白色为内容边界
        bg = Image.new("RGB", img.size, (255, 255, 255))
        diff = Image.new("RGB", img.size)
        from PIL import ImageChops
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        if bbox is None:
            raise RuntimeError("长图渲染为空")
        bottom = bbox[3]
        if bottom >= height - 3 and height < 64000:
            height *= 2
            shutil.rmtree(tmp_dir / "profile", ignore_errors=True)
            continue
        # 裁剪左右/上下的白色边距
        img = img.crop((max(bbox[0] - 2, 0), max(bbox[1] - 2, 0),
                        min(bbox[2] + 2, img.width), min(bottom + 2, img.height)))
        img.save(PNG_PATH)
        print(f"[OK] 长图: {PNG_PATH} ({img.width}x{img.height})")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return PNG_PATH
    raise RuntimeError("长图高度超出上限")


if __name__ == "__main__":
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    generate_pdf()
    render_longpage()
    print("完成：summary.pdf 与 longpage.png 已生成于 docs/summary/")
