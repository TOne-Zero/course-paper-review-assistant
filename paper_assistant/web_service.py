"""React 本机接口与静态页面服务；复用现有解析、评价、校验和导出链路。"""
from __future__ import annotations

import copy
import json
import math
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from paper_assistant.analysis_service import analyze_document
from paper_assistant.api_transport import HTTPChatTransport, validate_api_settings
from paper_assistant.batch import BatchPaper, MAX_BATCH_BYTES, MAX_BATCH_FILES, export_batch
from paper_assistant.config import PROJECT_ROOT, Settings, load_settings
from paper_assistant.criteria_store import CriteriaStore
from paper_assistant.rubric_defaults import default_score_bands, weighted_rubric
from paper_assistant.model_configuration import save_model_settings
from paper_assistant.document_parser import parse_document, validate_document
from paper_assistant.history_store import HistoryStore
from paper_assistant.privacy import configure_private_logging
from paper_assistant.providers import PROVIDERS, provider_for_url, resolve_api_key
from paper_assistant.report_exporter import export_markdown, report_data
from paper_assistant.rubrics import load_rubrics, parse_rubric_config, rubric_to_dict
from paper_assistant.schemas import AssistantError
from paper_assistant.validator import parse_model_json
from paper_assistant.teacher_review import add_teacher_edit, confirm_review, review_summary


@dataclass
class Session:
    mode: str
    rubric: object
    papers: list = field(default_factory=list)
    snapshots: dict = field(default_factory=dict)
    running: bool = False
    pause: bool = False
    generation: int = 0
    progress: str = ''
    touched: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=threading.RLock)


class WebApplication:
    def __init__(self, *, env_path=None, settings=None, analyzer=analyze_document, criteria_directory=None, history_path=None):
        self.rubrics = load_rubrics()
        self.criteria_store = CriteriaStore(criteria_directory or (Path(env_path).parent / 'criteria' if env_path else PROJECT_ROOT / 'rubrics' / 'user_settings'), self.rubrics)
        self.history = HistoryStore(history_path or PROJECT_ROOT / '.runtime' / 'history.db')
        self.catalogs, self.active_ids = {}, {}
        for mode in ('real', 'mock'):
            self.catalogs[mode], self.active_ids[mode] = self.criteria_store.load(mode)
        self.sessions = {}
        self.lock = threading.RLock()
        self.config_lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='paper-review')
        self.env_path = env_path
        self.analyzer = analyzer
        try:
            self.model_settings = settings or load_settings(mode='real')
        except AssistantError:
            self.model_settings = Settings(mode='real')

    def session(self, token, mode):
        with self.lock:
            now = time.monotonic()
            for key, value in list(self.sessions.items()):
                if not value.running and now - value.touched > 12 * 3600:
                    del self.sessions[key]
            key = (token, mode)
            if key not in self.sessions:
                if len(self.sessions) >= 20:
                    raise AssistantError('本机会话已满，请清空不用的会话或重新启动。')
                self.sessions[key] = Session(mode, next(r for r in self.catalogs[mode] if r.id == self.active_ids[mode]))
            session = self.sessions[key]
            session.touched = now
            return session

    def model_public(self):
        with self.config_lock:
            settings = self.model_settings
            try:
                validate_api_settings(settings)
                configured = True
            except AssistantError:
                configured = False
            return dict(provider=provider_for_url(settings.model_base_url), url=settings.model_base_url,
                        model=settings.model_name, key='', keySaved=bool(settings.model_api_key), configured=configured)

    def state(self, session):
        with session.lock:
            papers = [self.paper_view(paper, session.snapshots[paper.key], session) for paper in session.papers]
            return dict(mode=session.mode, papers=papers, model=self.model_public(),
                        rubric=rubric_to_dict(session.rubric), rubrics=[rubric_to_dict(r) for r in self.catalogs[session.mode]],
                        rubricPresets=[rubric_to_dict(r) for r in self.rubrics],
                        providers=[dict(name=p.name, url=p.base_url, documentation=p.documentation, note=p.note) for p in PROVIDERS],
                        running=session.running, pauseRequested=session.pause, progress=session.progress,
                        bytes=sum(len(p.content) for p in session.papers))

    def paper_view(self, paper, snapshot, session):
        document, run = snapshot.get('document'), snapshot.get('analysis_run')
        status = snapshot.get('status', 'queued')
        data, effective = None, None
        if run:
            data = report_data(run.result, snapshot.get('teacher_history', []), snapshot.get('teacher_confirmation'))
            effective = data['teacher_review']
        title = Path(paper.name).stem
        return dict(id=paper.key, name=paper.name, title=title, student='待核对', studentId='', status=status,
                    isUserFile=True, bytes=len(paper.content), error=snapshot.get('error', ''),
                    scores=[None if d['score'] is None else d['score'] / d['max_score'] * 100 for d in effective['dimensions']] if effective else [None] * len(session.rubric.dimensions),
                    totalScore=effective['total_score'] if effective else None,
                    reviewed=bool(effective and effective['confirmed']), teacherNote=snapshot.get('teacher_note', ''),
                    report=data, live=copy.deepcopy(snapshot.get('live')), pages=[dict(number=p.number, text=p.text, status=p.status) for p in document.pages] if document else [],
                    parsing=dict(status=document.parsing_status, warnings=list(document.warnings)) if document else None)

    @staticmethod
    def idle(session):
        if session.running:
            raise AssistantError('当前评阅尚未结束，请先暂停并等待本篇完成。')

    def upload(self, session, files):
        with session.lock:
            self.idle(session)
            if not files or len(files) + len(session.papers) > MAX_BATCH_FILES:
                raise AssistantError('每批最多10篇，请减少文件。')
            if sum(len(c) for _, c in files) + sum(len(p.content) for p in session.papers) > MAX_BATCH_BYTES:
                raise AssistantError('本批次不能超过50 MB。')
            for name, content in files:
                validate_document(content,name)
                if len(content) > min(20, self.model_settings.max_pdf_mb) * 1024 * 1024:
                    raise AssistantError('单篇论文不能超过20 MB或本机设置的上限。')
            additions = []
            for name, content in files:
                paper = BatchPaper(uuid4().hex, Path(name.replace('\\', '/')).name[:200], content)
                snapshot = {'status': 'queued'}
                try:
                    document = parse_document(content, paper.name, replace(self.model_settings, mode='mock'))
                    snapshot['document'] = document
                    if not document.can_analyze:
                        snapshot.update(status='failed', error='未提取到足够可靠文字，请检查Word正文或使用可搜索PDF；扫描图片需先OCR。')
                except AssistantError as error:
                    snapshot.update(status='failed', error=str(error))
                additions.append((paper, snapshot))
            for paper, snapshot in additions:
                session.papers.append(paper)
                session.snapshots[paper.key] = snapshot

    def set_rubric(self, session, payload):
        with self.lock, ExitStack() as stack:
            base = next((r for r in self.catalogs[session.mode] if r.id == payload.get('id')), None)
            if base is None:
                raise AssistantError('评分标准不存在。')
            affected = [s for s in self.sessions.values() if s.mode == session.mode and (s is session or s.rubric.id == base.id)]
            for value in affected:
                stack.enter_context(value.lock)
                self.idle(value)
            data = rubric_to_dict(base)
            editing = 'dimensions' in payload
            if editing:
                if payload.get('confirm') is not True:
                    raise AssistantError('请先确认修改评分条件会清除已有评分与复核。')
                if payload.get('expectedVersion') != base.version:
                    raise AssistantError('评分标准已被其他页面更新，请关闭设置并重新加载后再编辑。')
                dimensions = payload['dimensions']
                if not isinstance(dimensions, list) or len(dimensions) != len(base.dimensions):
                    raise AssistantError('评分维度数量不匹配。')
                for item, incoming in zip(data['dimensions'], dimensions):
                    if not isinstance(incoming, dict) or incoming.get('id') != item['id'] or incoming.get('name') != item['name']:
                        raise AssistantError('评分维度标识或顺序不匹配。')
                    text, scores = incoming.get('detailText'), incoming.get('detailScores')
                    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
                        raise AssistantError('每个维度的细则合计须为1–4000个字符。')
                    checks = [part.strip() for part in re.split(r'[;；\r\n]+', text) if part.strip()]
                    if not isinstance(scores, list) or len(scores) != len(checks) or not scores:
                        raise AssistantError('每条细则必须有对应分值。')
                    if checks != item['checklist']:
                        item['description'] = text.strip()
                        item['score_bands'] = default_score_bands('教师当前设定的本维度检查要求')
                    item.update(max_score=incoming.get('weight'), checklist=checks, checklist_scores=scores)
            elif 'weights' in payload:  # 兼容原本机客户端；新版编辑使用完整dimensions。
                weights = payload['weights']
                if not isinstance(weights, list) or len(weights) != len(base.dimensions):
                    raise AssistantError('评分维度数量不匹配。')
                for item, weight in zip(data['dimensions'], weights):
                    if item['max_score'] != weight:
                        item.pop('checklist_scores', None)
                    item['max_score'] = weight
            elif payload.get('select') is not True:
                raise AssistantError('请选择标准或提交完整评分细则。')
            candidate = weighted_rubric(parse_rubric_config(data))
            if candidate != base:
                candidate = replace(candidate, version='web-' + uuid4().hex[:16])
            catalog = tuple(candidate if r.id == base.id else r for r in self.catalogs[session.mode])
            self.criteria_store.save(session.mode, catalog, candidate.id)
            self.catalogs[session.mode], self.active_ids[session.mode] = catalog, candidate.id
            for value in affected:
                if candidate == value.rubric:
                    continue
                value.rubric = candidate
                for snapshot in value.snapshots.values():
                    for key in ('analysis_run', 'teacher_history', 'teacher_confirmation', 'teacher_note', 'live'):
                        snapshot.pop(key, None)
                    if snapshot.get('document') and snapshot['document'].can_analyze:
                        snapshot.update(status='queued', error='')
                value.progress = '评分条件已更新，旧评分已清除，请重新评阅。'

    def save_model(self, payload):
        with self.lock:
            self._save_model_locked(payload)

    def _save_model_locked(self, payload):
        with self.lock, self.config_lock:
            if any(s.running and s.mode == 'real' for s in self.sessions.values()):
                raise AssistantError('正式评阅正在运行，请暂停并等待当前篇完成后再修改模型配置。')
            old = self.model_settings
            url, name, key = (payload.get(k, '') for k in ('url', 'model', 'key'))
            if not all(isinstance(v, str) for v in (url, name, key)):
                raise AssistantError('配置字段必须是文本。')
            candidate = replace(old, mode='real', model_base_url=url.strip(), model_name=name.strip(),
                model_api_key=resolve_api_key(url, key, {'MODEL_BASE_URL': old.model_base_url, 'MODEL_API_KEY': old.model_api_key}))
            validate_api_settings(candidate)
            save_model_settings(candidate, env_path=self.env_path)
            self.model_settings = candidate
        if candidate != old or candidate.model_api_key != old.model_api_key:
            for session in list(self.sessions.values()):
                if session.mode != 'real':
                    continue
                with session.lock:
                    for snapshot in session.snapshots.values():
                        for key in ('analysis_run', 'teacher_history', 'teacher_confirmation', 'teacher_note', 'live'):
                            snapshot.pop(key, None)
                        if snapshot.get('document') and snapshot['document'].can_analyze:
                            snapshot.update(status='queued', error='')
                    session.progress = '模型配置已更新，请重新评阅。'

    def start(self, session, consent):
        with self.lock, session.lock:
            self.idle(session)
            if session.mode == 'real':
                validate_api_settings(self.model_settings)
                if consent is not True:
                    raise AssistantError('请确认将本批论文文本发送至已配置的模型服务。')
            pending = [p for p in session.papers if session.snapshots[p.key].get('document')
                       and session.snapshots[p.key]['document'].can_analyze
                       and (not session.snapshots[p.key].get('analysis_run')
                            or (session.snapshots[p.key]['analysis_run'].result.data['total_score'] is None
                                and not session.snapshots[p.key].get('teacher_history')))]
            if not pending:
                raise AssistantError('没有可评阅的论文，请先上传包含正文的Word或可搜索文字的PDF。')
            session.running, session.pause = True, False
            session.progress = '准备评阅'
            settings = replace(self.model_settings, mode=session.mode) if session.mode == 'real' else load_settings(mode='mock')
            self.executor.submit(self._run, session, pending, session.rubric, settings, session.generation)

    def _run(self, session, papers, rubric, settings, generation):
        try:
            for index, paper in enumerate(papers, 1):
                with session.lock:
                    if session.pause or session.generation != generation:
                        break
                    snapshot = session.snapshots[paper.key]
                    snapshot.update(status='processing', error='')
                    snapshot['live'] = {'stage': '准备读取论文', 'phase': 'connecting', 'startedAt': round(time.time()*1000),
                                        'updatedAt': round(time.time()*1000), 'reasoningCharacters': 0, 'outputCharacters': 0,
                                        'draft': '', 'streaming': None, 'events': []}
                    document = snapshot['document']
                def progress(message):
                    with session.lock:
                        session.progress = f'{index}/{len(papers)} · {paper.name} · {message}'
                        live = snapshot['live']
                        live['stage'] = message
                        live['updatedAt'] = round(time.time()*1000)
                        live['events'] = [*live['events'], {'text': message, 'at': live['updatedAt']}][-50:]
                def stream(event):
                    with session.lock:
                        live = snapshot['live']
                        live['updatedAt'] = round(time.time()*1000)
                        if event['kind'] == 'start':
                            live.update(phase='connecting', draft='', reasoningCharacters=0, outputCharacters=0, streaming=None)
                        elif event['kind'] == 'reasoning':
                            live.update(phase='analyzing', reasoningCharacters=event['characters'], streaming=True)
                        elif event['kind'] == 'output':
                            text = event['text']
                            if settings.model_api_key and settings.model_api_key in text:
                                return
                            notes = []
                            for match in re.finditer(r'"(?:reason|note)"\s*:\s*"((?:[^"\\]|\\.)*)', text):
                                try:
                                    value = json.loads('"' + match.group(1) + '"')
                                    if value: notes.append(value)
                                except ValueError:
                                    continue
                            live.update(phase='validating' if event.get('final') else 'generating', draft='\n\n'.join(notes)[-12000:],
                                        outputCharacters=len(text), streaming=event.get('streaming'))
                try:
                    run = self.analyzer(document, rubric, settings, allow_cloud=session.mode == 'real', progress=progress, on_stream=stream)
                    with session.lock:
                        snapshot['analysis_run'] = run
                        snapshot['status'] = 'review' if any(d['needs_teacher_review'] or d['score'] is None for d in run.result.data['dimensions']) else 'done'
                        snapshot['live'].update(phase='complete', stage='评阅完成，等待教师复核')
                except AssistantError as error:
                    with session.lock:
                        message = str(error).replace(settings.model_api_key, '[密钥已隐藏]') if settings.model_api_key else str(error)
                        snapshot.update(status='failed', error=message)
                        snapshot['live'].update(phase='failed', stage='评阅未完成')
                except Exception:
                    with session.lock:
                        snapshot.update(status='failed', error='评阅失败，请检查模型配置后重新尝试。')
                        snapshot['live'].update(phase='failed', stage='评阅未完成')
        finally:
            with session.lock:
                session.running = False
                session.progress = '后续任务已暂停，当前篇已完成。' if session.pause else '本批评阅已结束；失败或缺分项请复核。'

    def review(self, session, paper_id, payload):
        with session.lock:
            self.idle(session)
            snapshot = session.snapshots.get(paper_id)
            if not snapshot or not snapshot.get('analysis_run'):
                raise AssistantError('这篇论文尚无评阅结果。')
            run = snapshot['analysis_run']
            if payload.get('evaluationId') != run.result.data['evaluation_id']:
                raise AssistantError('评分已更新，请刷新页面后重新复核。')
            scores, note = payload.get('scores'), payload.get('note')
            if not isinstance(scores, list) or len(scores) != len(run.rubric.dimensions):
                raise AssistantError('复核维度数量不匹配。')
            history = snapshot.get('teacher_history', [])
            for dimension, ratio in zip(run.rubric.dimensions, scores):
                if ratio is not None and (isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 <= ratio <= 100):
                    raise AssistantError('复核分数必须在各维度范围内。')
                score = None if ratio is None else round(ratio * dimension.max_score / 100, 2)
                history = add_teacher_edit(run.result, history, dimension.id, score, note, note)
            snapshot['teacher_history'], snapshot['teacher_note'] = history, note.strip()
            snapshot['teacher_confirmation'] = confirm_review(run.result, history) if review_summary(run.result, history)['total_score'] is not None else None
            snapshot['status'] = 'done' if snapshot['teacher_confirmation'] else 'review'

    def export(self, session, ids=None):
        with session.lock:
            papers = session.papers if ids is None else [p for p in session.papers if p.key in ids]
            if not any(session.snapshots[p.key].get('analysis_run') for p in papers):
                raise AssistantError('没有可导出的报告。')
            snapshots = {key: dict(value, analysis_error=value.get('error', '')) for key, value in session.snapshots.items()}
            return export_batch(papers, snapshots)

    def archives(self, session):
        return self.history.payload(session.mode)

    def archive_batch(self, session, payload):
        with session.lock:
            self.idle(session)
            records, skipped = [], 0
            for paper in session.papers:
                snapshot = session.snapshots.get(paper.key, {})
                run = snapshot.get('analysis_run')
                if run is None:
                    skipped += 1
                    continue
                history, confirmation = snapshot.get('teacher_history', []), snapshot.get('teacher_confirmation')
                try:
                    data = report_data(run.result, history, confirmation)
                    markdown = export_markdown(run.result, history, confirmation).decode('utf-8')
                except AssistantError:
                    skipped += 1
                    continue
                review = data['teacher_review']
                if review['total_score'] is None:
                    skipped += 1
                    continue
                maximum = data.get('max_total_score') or 100
                raw = round(review['total_score'] / maximum * 100, 2)
                records.append({'name': paper.name, 'title': Path(paper.name.replace('\\', '/')).stem[:200],
                                'raw_total': raw, 'reviewed': bool(review['confirmed']),
                                'teacher_note': snapshot.get('teacher_note', ''),
                                'dimensions': [{'id': d['dimension_id'], 'name': d['name'], 'score': d['score'], 'max_score': d['max_score']}
                                               for d in review['dimensions']],
                                'report_md': markdown,
                                'report_json': json.dumps(data, ensure_ascii=False, allow_nan=False)})
            if not records:
                raise AssistantError('没有可归档的完整评分；请先完成评阅并补齐缺分维度。')
            result = self.history.create_batch(session.mode,
                                               {**payload, 'rubricName': session.rubric.name, 'rubricVersion': session.rubric.version}, records)
            return {**result, 'skipped': skipped}

    def archive_detail(self, session, class_id):
        return self.history.detail(session.mode, class_id)

    def archive_normalize(self, session, class_id, payload):
        return self.history.normalize(session.mode, class_id, payload)

    def delete_archive_class(self, session, class_id):
        self.history.delete_class(session.mode, class_id)

    def delete_archive_batch(self, session, batch_id):
        self.history.delete_batch(session.mode, batch_id)

    def export_archive(self, session, class_id):
        return self.history.export_class(session.mode, class_id)


def make_server(app, host='127.0.0.1', port=8765, dist=None):
    dist = (Path(dist) if dist else PROJECT_ROOT / 'frontend' / 'dist-app').resolve()
    class Handler(BaseHTTPRequestHandler):
        server_version = 'PaperAssistant'
        def log_message(self, *_):
            pass

        def _send(self, status, body, content_type='application/json; charset=utf-8', cookie=None, attachment=False, filename='paper-reports.zip'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', "frame-ancestors 'self'")
            if cookie:
                self.send_header('Set-Cookie', f'paper_session={cookie}; HttpOnly; SameSite=Strict; Path=/')
            if attachment:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, value, cookie=None):
            self._send(status, json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), cookie=cookie)

        def _body(self, maximum=100_000):
            if self.headers.get('Transfer-Encoding'):
                raise AssistantError('不支持此传输方式。')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise AssistantError('请求长度无效。') from None
            if not 0 < length <= maximum:
                raise AssistantError('请求为空或超过大小限制。')
            self.connection.settimeout(60)
            content = self.rfile.read(length)
            if len(content) != length:
                raise AssistantError('上传中断，请重新选择文件。')
            return content

        def _payload(self):
            try:
                payload = json.loads(self._body())
                if not isinstance(payload, dict):
                    raise ValueError()
                return payload
            except (ValueError, UnicodeError):
                raise AssistantError('请求数据格式无效。') from None

        def _session(self):
            host_header = self.headers.get('Host', '')
            parts = urlsplit('http://' + host_header)
            if parts.hostname not in ('localhost', '127.0.0.1', '::1'):
                raise AssistantError('此应用只允许本机访问。')
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://{host_header}', 'http://127.0.0.1:5173', 'http://localhost:5173'):
                raise AssistantError('不接受其它网站发起的请求。')
            if self.command != 'GET' and self.headers.get('X-Paper-Request') != '1':
                raise AssistantError('缺少应用请求标识，请刷新页面。')
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get('Cookie', ''))
            except Exception:
                pass
            token = cookies.get('paper_session')
            token = token.value if token and re.fullmatch(r'[a-f0-9]{64}', token.value) else secrets.token_hex(32)
            mode = self.headers.get('X-Review-Mode', 'real')
            if mode not in ('real', 'mock'):
                raise AssistantError('评阅模式无效。')
            return app.session(token, mode), token

        def _handle(self):
            path = urlsplit(self.path).path
            if not path.startswith('/api/'):
                if self.command != 'GET':
                    self._json(405, {'error': '不支持此操作。'}); return
                import mimetypes
                relative = unquote(path).lstrip('/')
                target = (dist / relative).resolve()
                if not target.is_relative_to(dist) or any(part.startswith('.') for part in Path(relative).parts):
                    self._json(404, {'error': '页面不存在。'}); return
                if not target.is_file():
                    if Path(relative).suffix:
                        self._json(404, {'error': '文件不存在。'}); return
                    target = dist / 'index.html'
                if not target.is_file():
                    self._json(503, {'error': '前端尚未构建，请运行npm run build。'}); return
                self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream'); return
            session, cookie = self._session()
            if self.command == 'GET' and path == '/api/state':
                self._json(200, app.state(session), cookie); return
            if self.command == 'GET' and path == '/api/reports':
                ids = parse_qs(urlsplit(self.path).query).get('id')
                self._send(200, app.export(session, ids), 'application/zip', attachment=True); return
            if self.command == 'GET' and path == '/api/archives':
                self._json(200, app.archives(session), cookie); return
            if self.command == 'POST' and path == '/api/archives':
                self._json(200, app.archive_batch(session, self._payload()), cookie); return
            if path.startswith('/api/archives/'):
                rest = path[len('/api/archives/'):]
                head, _, tail = rest.partition('/')
                if head == 'classes' and tail:
                    class_id, _, action = tail.partition('/')
                    if self.command == 'GET' and not action:
                        self._json(200, app.archive_detail(session, class_id), cookie); return
                    if self.command == 'POST' and action == 'normalize':
                        self._json(200, app.archive_normalize(session, class_id, self._payload()), cookie); return
                    if self.command == 'GET' and action == 'export':
                        self._send(200, app.export_archive(session, class_id), 'application/zip',
                                   attachment=True, filename='class-scores.zip'); return
                    if self.command == 'DELETE' and not action:
                        app.delete_archive_class(session, class_id)
                        self._json(200, {'deleted': True}, cookie); return
                if head == 'batches' and tail and self.command == 'DELETE':
                    app.delete_archive_batch(session, tail)
                    self._json(200, {'deleted': True}, cookie); return
                self._json(404, {'error': '接口不存在。'}); return
            if self.command == 'POST' and path == '/api/upload':
                content_type = self.headers.get('Content-Type', '')
                if not content_type.startswith('multipart/form-data;'):
                    raise AssistantError('上传格式无效。')
                message = BytesParser(policy=policy.default).parsebytes(('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + self._body(MAX_BATCH_BYTES + 1024 * 1024))
                files = []
                if message.is_multipart():
                    for part in message.iter_parts():
                        if part.get_filename():
                            files.append((part.get_filename(), part.get_payload(decode=True) or b''))
                app.upload(session, files)
            elif self.command == 'POST' and path == '/api/model':
                app.save_model(self._payload())
            elif self.command == 'POST' and path == '/api/model/test':
                payload = self._payload()
                with app.config_lock:
                    settings = app.model_settings
                if any(name in payload for name in ('url', 'model', 'key')):
                    url, model, key = (payload.get(name, '') for name in ('url', 'model', 'key'))
                    if not all(isinstance(value, str) for value in (url, model, key)):
                        raise AssistantError('配置字段必须是文本。')
                    settings = replace(settings, model_base_url=url.strip(), model_name=model.strip(),
                        model_api_key=resolve_api_key(url, key, {'MODEL_BASE_URL': settings.model_base_url, 'MODEL_API_KEY': settings.model_api_key}))
                schema = {'type': 'object', 'properties': {'reply': {'type': 'string'}}, 'required': ['reply'], 'additionalProperties': False}
                started = time.monotonic()
                content = HTTPChatTransport(replace(settings, model_max_output_tokens=128)).complete(
                    [{'role':'system','content':'Return a JSON object.'},{'role':'user','content':'Reply with {"reply":"OK"}.'}], schema)
                try:
                    try:
                        answer = parse_model_json(content)
                        reply = answer.get('reply') if isinstance(answer, dict) else None
                    except AssistantError:
                        answer={}
                        reply=content.strip() if not content.lstrip().startswith(('{','[','```','<')) else None
                    if reply is None and isinstance(answer, dict) and answer.get('ok') is True:
                        reply = 'OK'
                    if not isinstance(reply, str) or not reply.strip() or len(reply) > 100:
                        raise ValueError()
                    if settings.model_api_key and settings.model_api_key in reply:
                        raise ValueError()
                except (ValueError, TypeError, AssistantError):
                    raise AssistantError('服务已响应，但没有返回有效的测试回复，请核对模型标识与兼容性。') from None
                self._json(200, {'message': '模型连接测试成功。', 'reply': reply.strip(), 'model': settings.model_name,
                                 'elapsedMs': round((time.monotonic() - started) * 1000)}); return
            elif self.command == 'POST' and path == '/api/rubric':
                app.set_rubric(session, self._payload())
            elif self.command == 'POST' and path == '/api/start':
                app.start(session, self._payload().get('consent'))
            elif self.command == 'POST' and path == '/api/pause':
                self._payload()
                with session.lock:
                    session.pause = True
                    session.progress = '将在当前篇完成后暂停后续任务。'
            elif self.command == 'POST' and path == '/api/clear':
                self._payload()
                with session.lock:
                    app.idle(session)
                    session.papers.clear(); session.snapshots.clear(); session.generation += 1; session.progress = ''
            elif self.command == 'DELETE' and path.startswith('/api/papers/'):
                with session.lock:
                    app.idle(session)
                    paper_id = path.rsplit('/', 1)[-1]
                    session.papers = [p for p in session.papers if p.key != paper_id]
                    session.snapshots.pop(paper_id, None)
            elif self.command == 'POST' and path.startswith('/api/reviews/'):
                app.review(session, path.rsplit('/', 1)[-1], self._payload())
            elif self.command == 'POST' and path == '/api/demo':
                self._payload()
                if session.mode != 'mock':
                    raise AssistantError('示例论文只可在模拟运行入口使用。')
                content = (PROJECT_ROOT / 'examples' / '演示论文_原创虚构.pdf').read_bytes()
                app.upload(session, [('演示论文_原创虚构.pdf', content)])
            else:
                self._json(404, {'error': '接口不存在。'}); return
            self._json(200, app.state(session), cookie)

        def _dispatch(self):
            try:
                self._handle()
            except AssistantError as error:
                message = str(error)
                key = app.model_settings.model_api_key
                if key:
                    message = message.replace(key, '[密钥已隐藏]')
                self._json(400, {'error': message})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self._json(500, {'error': '请求未完成，请重试或检查本机配置。'})
        do_GET = do_POST = do_DELETE = _dispatch

    return ThreadingHTTPServer((host, port), Handler)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    configure_private_logging()
    app = WebApplication()
    server = make_server(app, port=args.port)
    print(f'结课论文评价助手：http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.executor.shutdown(wait=True)


if __name__ == '__main__':
    main()
