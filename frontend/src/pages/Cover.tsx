import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Icon } from '../components/Icon';

const DOCUMENT_PAGES = [
  { number: '01', title: '研究问题', widths: [100, 94, 100, 82, 100, 96, 72] },
  { number: '02', title: '分析与讨论', widths: [96, 100, 86, 100, 94, 100, 67] },
  { number: '03', title: '结论与展望', widths: [100, 88, 100, 96, 100, 80, 62] },
];

function DocumentPages() {
  return <>{DOCUMENT_PAGES.map(page => <div className="cover-document-sheet" key={page.number}>
    <div className="document-running-head"><span>课程论文</span><span>{page.number}</span></div>
    <div className="document-title font-serif">{page.title}</div>
    <div className="document-byline" />
    <div className="document-abstract"><span className="font-serif">摘要</span><i /><i /><i /></div>
    <div className="document-columns">{[0, 1].map(column => <div key={column}>{[0, 1].map(paragraph => <div className="document-paragraph" key={paragraph}>{page.widths.map((width, line) => <i key={line} style={{ width: `${column ? Math.max(55, width - 5) : width}%` }} />)}</div>)}</div>)}</div>
    <div className="document-page-number font-serif">{page.number}</div>
  </div>)}</>;
}

export function Cover({ enter }: { enter: () => void }) {
  const surface = useRef<HTMLElement>(null);
  const [paused, setPaused] = useState(false);
  const [inactive, setInactive] = useState(document.hidden);
  const [typeReady, setTypeReady] = useState(false);
  useEffect(() => {
    let mounted = true;
    document.fonts.ready.then(() => { if (mounted) setTypeReady(true); });
    return () => { mounted = false; };
  }, []);
  useEffect(() => {
    let inView = true;
    const update = () => setInactive(document.hidden || !inView);
    const observer = new IntersectionObserver(([entry]) => { inView = entry.isIntersecting; update(); });
    if (surface.current) observer.observe(surface.current);
    document.addEventListener('visibilitychange', update);
    return () => { observer.disconnect(); document.removeEventListener('visibilitychange', update); };
  }, []);
  return <div className="cover animate-page-in">
    <header className="cover-masthead">
      <span className="font-serif text-xl font-medium">结课论文评价助手</span>
      <span className="preview-label">结课论文评阅</span>
    </header>
    <main className="cover-body" ref={surface} data-motion={paused || inactive ? 'paused' : 'running'}>
      <div className="cover-light" aria-hidden="true" />
      <div className="cover-composition">
        <div className="cover-copy">
          <h1 className="cover-title font-serif text-display" aria-label="让每一篇论文，被认真读过。" data-type-ready={typeReady}>
            {['让每一篇论文，', '被认真读过。'].map((line, row) => <span className="cover-title-line" aria-hidden="true" key={line}>{Array.from(line).map((letter, index) => <span className="cover-title-glyph" key={index} style={{ '--letter-index': index + row * 7 } as CSSProperties}>{letter}</span>)}</span>)}
          </h1>
          <div className="cover-action-row">
            <button className="text-action cover-enter" onClick={enter}>开始评阅 <Icon name="arrow" size={23} /></button>
            <span className="text-caption text-muted">批量阅读 · 有据评价 · 教师复核</span>
          </div>
        </div>
        <div className="cover-documents">
          <div className="cover-document-window" aria-hidden="true">
            <div className="cover-document-track">{[0, 1].map(copy => <div className="cover-document-group" key={copy}><DocumentPages /></div>)}</div>
          </div>
          <button className="cover-motion-toggle" type="button" onClick={() => setPaused(value => !value)} aria-label={paused ? '播放开屏动画' : '暂停开屏动画'} title={paused ? '播放动画' : '暂停动画'}><Icon name={paused ? 'play' : 'pause'} size={16} /></button>
        </div>
      </div>
    </main>
    <footer className="cover-footer">
      <span>单批至多 10 篇论文</span><span>AI辅助评价，最终成绩由教师确定</span>
    </footer>
  </div>;
}
