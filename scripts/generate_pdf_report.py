"""生成 PDF 测试报告。

从 JUnit XML 和测试计划 Markdown 生成格式化 PDF 报告。
用法: python scripts/generate_pdf_report.py
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from fpdf import FPDF

REPORT_DIR = Path(__file__).resolve().parent.parent / "docs"
XML_PATH = Path(__file__).resolve().parent.parent / "test_results.xml"


# 测试场景分类
SCENARIO_CATEGORIES = {
    "认证": ("TestAuth", "TC-01 ~ TC-03"),
    "陪驾订单": ("TestOrders", "TC-04 ~ TC-08"),
    "支付流程": ("TestPayments", "TC-09 ~ TC-12"),
    "教练确认执行": ("TestCoachExecution", "TC-13 ~ TC-16"),
    "评价": ("TestReviews", "TC-17 ~ TC-18"),
    "争议与取消": ("TestDispute", "TC-19 ~ TC-21"),
    "限流保护": ("TestRateLimit", "TC-22 ~ TC-23"),
    "通知系统": ("TestNotification", "TC-24 ~ TC-25"),
    "安全性": ("TestSecurity", "TC-26 ~ TC-28"),
    "全流程": ("TestFullFlow", "全流程"),
}


class TestReport(FPDF):
    def __init__(self):
        super().__init__()
        # 注册中文字体（Windows 系统自带 Microsoft YaHei）
        font_path = "C:/Windows/Fonts/msyh.ttc"
        self.add_font("zh", "", font_path)
        self.add_font("zh", "B", font_path)
        # 英文用 Helvetica
        self.add_font("zh-en", "", font_path)

    def header(self):
        if self.page_no() > 1:
            self.set_font("zh", "", 8)
            self.cell(0, 8, "UMCP 陪驾业务测试报告", align="L")
            self.cell(0, 8, f"第 {self.page_no()} 页", align="R", new_x="LMARGIN", new_y="NEXT")
            self.line(10, 16, 200, 16)
            self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("zh", "", 7)
        self.cell(0, 10, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", align="C")

    def chapter_title(self, title: str):
        self.set_font("zh", "B", 14)
        self.set_text_color(30, 60, 120)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(30, 60, 120)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def chapter_body(self, text: str):
        self.set_font("zh", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def add_summary_table(self, total: int, passed: int, failed: int, skipped: int, time_sec: float):
        cols = [("指标", 60), ("数值", 60)]
        self.set_font("zh", "B", 10)
        for label, w in cols:
            self.cell(w, 8, label, border=1, align="C")
        self.ln()
        self.set_font("zh", "", 10)
        for row in [
            ("总用例数", str(total)),
            ("通过", str(passed)),
            ("失败", str(failed)),
            ("跳过", str(skipped)),
            ("执行时间", f"{time_sec:.1f}s"),
            ("通过率", f"{passed / total * 100:.1f}%" if total > 0 else "N/A"),
        ]:
            label, val = row
            color = (0, 150, 0) if "通过" in label or "100" in val else (
                (200, 0, 0) if "失败" in label and failed > 0 else (50, 50, 50)
            )
            self.set_text_color(*color)
            self.cell(60, 7, label, border=1)
            self.cell(60, 7, val, border=1, align="C")
            self.ln()

    def add_scenario_results(self, results: list[dict]):
        self.set_font("zh", "B", 9)
        col_widths = [50, 60, 20, 20, 40]
        headers = ["测试场景", "测试用例", "状态", "耗时", "覆盖范围"]
        for h, w in zip(headers, col_widths):
            self.cell(w, 7, h, border=1, align="C")
        self.ln()
        self.set_font("zh", "", 8)
        for r in results:
            status = r["status"]
            status_color = (0, 150, 0) if status == "PASS" else (200, 0, 0)
            self.set_text_color(*status_color)
            self.cell(col_widths[0], 6, r["category"], border=1)
            self.cell(col_widths[1], 6, r["test_name"], border=1)
            self.cell(col_widths[2], 6, status, border=1, align="C")
            self.cell(col_widths[3], 6, f"{r['time']:.2f}s", border=1, align="C")
            self.set_text_color(50, 50, 50)
            self.cell(col_widths[4], 6, r["coverage"], border=1)
            self.ln()


def parse_xml(xml_path: str) -> tuple:
    """解析 JUnit XML，返回 (total, passed, failed, skipped, time, test_cases)。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    testsuite = root[0] if root.tag == "testsuites" else root

    total = int(testsuite.get("tests", 0))
    errors = int(testsuite.get("errors", 0))
    failures = int(testsuite.get("failures", 0))
    skipped = int(testsuite.get("skipped", 0))
    time_sec = float(testsuite.get("time", 0))
    passed = total - errors - failures - skipped

    test_cases = []
    for tc in testsuite.findall(".//testcase"):
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        time = float(tc.get("time", 0))
        failure = tc.find("failure")
        error = tc.find("error")
        status = "PASS"
        if failure is not None or error is not None:
            status = "FAIL"
        test_cases.append({
            "classname": classname,
            "name": name,
            "time": time,
            "status": status,
        })

    return total, passed, failures, skipped, time_sec, test_cases


def match_category(classname: str) -> tuple[str, str]:
    """根据 classname 匹配场景分类。"""
    for cat, (prefix, coverage) in SCENARIO_CATEGORIES.items():
        if prefix in classname:
            return cat, coverage
    return "其他", "-"


def generate_pdf():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    total, passed, failed, skipped, time_sec, test_cases = parse_xml(str(XML_PATH))

    pdf = TestReport()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ========= 封面 =========
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("zh", "B", 28)
    pdf.set_text_color(30, 60, 120)
    pdf.cell(0, 15, "UMCP 陪驾业务测试报告", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("zh", "", 14)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, "通用市场交易协调引擎 v2.0.0", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.cell(0, 10, f"测试日期: 2026-08-15", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, "支付模式: Mock 支付（开发环境）", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.set_font("zh", "B", 16)
    pdf.set_text_color(0, 150, 0)
    pdf.cell(0, 12, f"  {passed}/{total} 测试通过 ({passed / total * 100:.1f}%)" if total > 0 else "N/A", align="C", new_x="LMARGIN", new_y="NEXT")

    # ========= 测试摘要 =========
    pdf.add_page()
    pdf.chapter_title("一、测试摘要")
    pdf.add_summary_table(total, passed, failed, skipped, time_sec)
    pdf.ln(10)

    pdf.set_font("zh", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.chapter_body("测试环境:")
    env_items = [
        "服务地址: http://localhost:8000",
        "API 前缀: /api/v1",
        "支付网关: MockGateway（模拟支付）",
        "短信通道: 开发模式（控制台输出）",
        "限流策略: 60s 窗口 / 100 次/IP",
        "数据存储: 内存仓储",
    ]
    for item in env_items:
        pdf.cell(10)
        pdf.cell(0, 6, f"  - {item}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ========= 场景结果 =========
    pdf.add_page()
    pdf.chapter_title("二、测试场景执行结果")

    scenario_results = []
    for tc in test_cases:
        cat, coverage = match_category(tc["classname"])
        scenario_results.append({
            "category": cat,
            "test_name": tc["name"],
            "status": tc["status"],
            "time": tc["time"],
            "coverage": coverage,
        })

    pdf.add_scenario_results(scenario_results)
    pdf.ln(5)

    # 汇总统计
    pdf.set_font("zh", "B", 10)
    pdf.set_text_color(30, 60, 120)
    pdf.cell(0, 8, "场景覆盖率统计:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("zh", "", 9)
    pdf.set_text_color(50, 50, 50)
    cat_stats: dict[str, list] = {}
    for r in scenario_results:
        cat_stats.setdefault(r["category"], []).append(r)
    for cat, cases in cat_stats.items():
        p = sum(1 for c in cases if c["status"] == "PASS")
        total_c = len(cases)
        coverage = SCENARIO_CATEGORIES.get(cat, ("", ""))[1]
        status_icon = "PASS" if p == total_c else "FAIL"
        pdf.cell(10)
        pdf.cell(0, 6, f"  [{status_icon}] {cat}: {p}/{total_c} 通过 ({coverage})", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ========= 失败详情 =========
    if failed > 0:
        pdf.chapter_title("三、失败用例详情")
        pdf.set_font("Courier", "", 8)
        pdf.set_text_color(200, 0, 0)
        tree = ET.parse(str(XML_PATH))
        for failure in tree.findall(".//failure"):
            parent = failure.getparent() if hasattr(failure, "getparent") else None
            if parent is None:
                for tc in tree.findall(".//testcase"):
                    if tc.find("failure") is failure:
                        parent = tc
                        break
            if parent is not None:
                msg = failure.get("message", "") or failure.text or ""
                pdf.multi_cell(0, 5, f"  [{parent.get('classname')}::{parent.get('name')}] {msg[:200]}")
                pdf.ln(2)
    else:
        pdf.add_page()
        pdf.chapter_title("三、失败用例详情")
        pdf.set_font("zh", "", 12)
        pdf.set_text_color(0, 150, 0)
        pdf.cell(0, 10, "  无失败用例，所有测试通过。", new_x="LMARGIN", new_y="NEXT")

    # ========= 已知问题 =========
    pdf.add_page()
    pdf.chapter_title("四、已知问题与注意事项")

    issues = [
        ("datetime.utcnow() 弃用警告", "仅日志警告，不影响业务", "下个版本统一迁移"),
        ("测试 JWT 密钥长度不足 32 字节", "仅测试环境警告", "生产环境已使用 32 字节密钥"),
        ("内存仓储重启后数据丢失", "开发测试无影响", "生产环境需配置 PostgreSQL"),
        ("短信为开发模式（控制台输出）", "生产环境需配置互亿无线 API", "参考 .env.example"),
        ("微信支付为 Mock 模式", "测试支付流程需 Mock 模式", "生产环境配置 WECHAT_* 参数"),
    ]

    pdf.set_font("zh", "B", 9)
    col_w = [55, 65, 65]
    for h, w in zip(["问题", "影响", "建议"], col_w):
        pdf.cell(w, 7, h, border=1, align="C")
    pdf.ln()
    pdf.set_font("zh", "", 8)
    for issue, impact, suggestion in issues:
        pdf.cell(col_w[0], 6, issue, border=1)
        pdf.cell(col_w[1], 6, impact, border=1)
        pdf.cell(col_w[2], 6, suggestion, border=1)
        pdf.ln()

    # ========= 保存 =========
    output_path = REPORT_DIR / "test_report.pdf"
    pdf.output(str(output_path))
    print(f"PDF 报告已生成: {output_path}")
    return output_path


if __name__ == "__main__":
    generate_pdf()