"""无真实个人资料的最小Word测试文件，含中文、表格和显式分页。"""
from io import BytesIO
from xml.sax.saxutils import escape
import zipfile


def make_docx():
    paragraphs=['原创虚构Word接口测试论文','摘要：本文仅用于验证Word论文上传和解析，所有场景均为虚构，不代表真实研究结论。',
                '一、研究问题：校园阅览室延长开放时间，是否改善学生阅读便利度？',
                '二、方法：采用虚构问卷与观察记录作描述性比较，不声称因果关系。']
    tail=['三、分析：虚构比较提示晚间到访便利度改善，但样本有限，不能外推。',
          '四、结论：建议小范围试点并继续收集反馈。本测试不要求真实访谈或实验数据。',
          '参考文献：此为接口测试，不提供可作为学术依据的真实参考文献。']
    body=''.join('<w:p><w:r><w:t>'+escape(p)+'</w:t></w:r></w:p>' for p in paragraphs)
    body+='<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="4000"/><w:gridCol w:w="4000"/></w:tblGrid><w:tr><w:tc><w:p><w:r><w:t>测试变量</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>虚构数值：3.8</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    body+='<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    body+=''.join('<w:p><w:r><w:t>'+escape(p)+'</w:t></w:r></w:p>' for p in tail)
    document='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
    output=BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml',document)
    return output.getvalue()
