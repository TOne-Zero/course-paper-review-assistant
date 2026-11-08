"""用 reportlab 重新生成原创虚构样例；仅需 requirements-demo.txt。"""

import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def main():
    root = Path(__file__).resolve().parents[1]
    source = json.loads((root / "examples" / "demo_paper.json").read_text(encoding="utf-8"))
    target = root / "examples" / "演示论文_原创虚构.pdf"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    body = ParagraphStyle("body", fontName="STSong-Light", fontSize=11, leading=18, wordWrap="CJK", spaceAfter=9)
    heading = ParagraphStyle("heading", parent=body, fontSize=13, leading=21, spaceBefore=8, textColor=colors.HexColor("#1D3557"))
    title = ParagraphStyle("title", parent=body, fontSize=17, leading=27, alignment=TA_CENTER, spaceAfter=15)
    note = ParagraphStyle("note", parent=body, fontSize=10, leading=16, textColor=colors.HexColor("#7A3E00"), spaceAfter=12)
    story = []
    for page_index, paragraphs in enumerate(source["pages"]):
        if page_index:
            story.append(PageBreak())
        for index, text in enumerate(paragraphs):
            style = title if page_index == 0 and index == 1 else note if page_index == 0 and index == 0 else heading if len(text) < 28 and not text.startswith("[") else body
            story.append(Paragraph(escape(text), style))
        if page_index == 0:
            story.append(Spacer(1, 8))
            story.append(Paragraph(escape(source["notice"]), note))
    def decorate(canvas, document):
        canvas.setFont("STSong-Light", 9)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(48, A4[1] - 30, "原创虚构演示样例 · 非真实学生论文")
        canvas.drawCentredString(A4[0] / 2, 27, f"演示用途 · 第 {document.page} 页")
    document = SimpleDocTemplate(str(target), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=51, bottomMargin=44,
                                 title=source["title"], author="虚构演示样例")
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    print(target)


if __name__ == "__main__":
    main()
