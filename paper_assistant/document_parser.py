"""PDF和Word统一入口；Word先在本机分页转换，模型仍只接收已提取文字。"""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile

from paper_assistant.config import PROJECT_ROOT
from paper_assistant.pdf_parser import PARSER_VERSION as PDF_VERSION, parse_pdf
from paper_assistant.schemas import AssistantError

PARSER_VERSION = 'documents-1.0+'+PDF_VERSION
SUPPORTED_EXTENSIONS = {'.pdf','.docx','.doc'}
_WORD_LOCK = threading.Lock()
_OLE = bytes.fromhex('D0CF11E0A1B11AE1')


def validate_document(content, filename):
    suffix=Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise AssistantError('请选择PDF或Word文件（.pdf、.docx、.doc）。')
    if not content:raise AssistantError('文件为空，请重新选择论文。')
    if suffix=='.pdf':
        if not content.lstrip().startswith(b'%PDF-'):raise AssistantError('文件内容不是有效的 PDF，请检查扩展名。')
    elif suffix=='.doc':
        if not content.startswith(_OLE):raise AssistantError('文件内容不是有效的Word .doc，请在Word中另存为.docx后上传。')
    else:
        if not content.startswith(b'PK'):raise AssistantError('Word文件已加密或格式与.docx扩展名不符，请解除保护或重新另存。')
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                items=archive.infolist();names={i.filename for i in items}
                if not {'[Content_Types].xml','word/document.xml'}.issubset(names):raise ValueError()
                if len(items)>5000 or sum(i.file_size for i in items)>100*1024*1024 or any(i.flag_bits&1 for i in items):raise ValueError()
                if any('vbaproject' in name.lower() for name in names):raise ValueError()
        except (ValueError,zipfile.BadZipFile,OSError):
            raise AssistantError('Word .docx内容无效、已加密或解压体积过大，请重新另存后上传。') from None


def _office_converter():
    candidate=shutil.which('soffice')
    if candidate:return candidate
    for base in (os.environ.get('ProgramFiles',''),os.environ.get('ProgramFiles(x86)','')):
        if base:
            path=Path(base)/'LibreOffice/program/soffice.exe'
            if path.is_file():return str(path)
    return None


def convert_word_to_pdf(content,suffix):
    """隔离临时文件，超时仅清理本次拥有的Word进程，不关闭用户文档。"""
    root=PROJECT_ROOT/'.runtime/word-conversion'
    if not root.resolve().is_relative_to(PROJECT_ROOT.resolve()):raise AssistantError('Word临时目录不在项目内，未开始转换。')
    root.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).with_name('word_to_pdf.ps1')
    with _WORD_LOCK, tempfile.TemporaryDirectory(prefix='paper-',dir=root) as temporary:
        work=Path(temporary);source=work/('document'+suffix);output=work/'document.pdf';owner=work/'word-owner.json'
        if not work.resolve().is_relative_to(root.resolve()):raise AssistantError('Word临时路径无效，未读取文件。')
        source.write_bytes(content);office=_office_converter()
        if office:
            command=[office,'-env:UserInstallation='+str((work/'profile').as_uri()),'--headless','--convert-to','pdf','--outdir',str(work),str(source)]
        elif os.name=='nt':
            command=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-InputPath',str(source),'-OutputPath',str(output),'-OwnerFile',str(owner)]
        else:
            raise AssistantError('本机未检测到Word转换服务，请安装LibreOffice后重新启动应用，或先将论文另存为PDF。')
        kwargs={'capture_output':True,'timeout':90}
        if os.name=='nt':kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
        try:
            result=subprocess.run(command,**kwargs)
            if result.returncode or not output.is_file():
                raise AssistantError('Word读取失败：请确认本机Word/LibreOffice可用，且文件未加密、未损坏；也可另存为.docx或PDF后重试。')
            if output.stat().st_size>100*1024*1024:raise AssistantError('Word转换后的文件过大，请缩减图片或拆分论文后重试。')
            return output.read_bytes()
        except subprocess.TimeoutExpired:
            raise AssistantError('Word分页转换超时，请关闭文件保护提示，或将论文另存为PDF后重试。') from None
        except OSError:
            raise AssistantError('无法启动本机Word转换服务，请检查Word或LibreOffice安装。') from None
        finally:
            if not office and os.name=='nt' and owner.exists():
                try:
                    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),'-OwnerFile',str(owner),'-CleanupOnly'],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError,subprocess.TimeoutExpired):pass


def parse_document(content,filename,settings):
    if len(content)>settings.max_pdf_mb*1024*1024:raise AssistantError(f'单篇论文不能超过{settings.max_pdf_mb} MB。')
    validate_document(content,filename)
    suffix=Path(filename).suffix.lower()
    if suffix=='.pdf':return parse_pdf(content,filename,settings)
    converted=convert_word_to_pdf(content,suffix)
    document=parse_pdf(converted,filename,replace(settings,max_pdf_mb=100))
    return replace(document,sha256=hashlib.sha256(content).hexdigest(),source=suffix[1:],parser_version=PARSER_VERSION,
                   warnings=('Word已在本机转换为PDF分页读取；引用页码对应本次转换版，可能随字体及排版变化。',*document.warnings))
