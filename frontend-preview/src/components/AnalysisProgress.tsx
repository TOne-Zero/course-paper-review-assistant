import { useEffect, useRef, useState } from 'react';
import type { LiveAnalysis } from '../model';

const phases = { connecting: '连接模型', analyzing: '模型分析中', generating: '正在生成', validating: '核对引用与分值', complete: '分析已结束', failed: '本次分析未完成' };
export function AnalysisProgress({ live, working }: { live: LiveAnalysis; working: boolean }) {
  const [now, setNow] = useState(Date.now());
  const output = useRef<HTMLDivElement>(null), follow = useRef(true);
  useEffect(() => { if (!working) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [working]);
  useEffect(() => { if (follow.current && output.current) output.current.scrollTop = output.current.scrollHeight; }, [live.draft]);
  const elapsed = Math.max(0, Math.floor(((working ? now : live.updatedAt) - live.startedAt) / 1000));
  return <section className="analysis-progress" aria-label="实时分析过程">
    <div className="analysis-progress-heading"><div className="analysis-phase" role="status">{working && <span className="paper-spinner" aria-hidden="true"/>}<span>{phases[live.phase]}</span></div><span className="analysis-elapsed font-serif">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span></div>
    <p className="analysis-current-stage">{live.stage}</p>
    <div className="analysis-progress-layout"><div className="analysis-generation">
      <div className="analysis-subheading"><h3 className="font-serif">评阅草稿</h3><span>{live.outputCharacters ? `已生成 ${live.outputCharacters.toLocaleString()} 字` : live.reasoningCharacters ? '正在分析材料与依据' : '等待模型返回'}</span></div>
      <div ref={output} className="analysis-draft" onScroll={() => { const element = output.current!; follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48; }}>
        {live.draft ? <p>{live.draft}</p> : <p className="analysis-waiting">{live.phase === 'analyzing' ? '模型正在梳理本阶段的材料与评分依据…' : working ? '生成内容将在这里逐步呈现…' : '本阶段没有可展示的生成片段。'}</p>}
      </div>
      <p className="analysis-draft-note">生成片段尚未校验，最终分数以评阅结果为准。{live.streaming === false ? '该服务一次性返回内容。' : ''}</p>
    </div><aside className="analysis-event-log" aria-label="分析阶段记录"><h3 className="font-serif">分析进度</h3><ol>{live.events.map((event, index) => <li key={`${event.at}-${index}`} className={index === live.events.length - 1 && working ? 'is-current' : ''}><span className="analysis-event-mark" aria-hidden="true"/><span>{event.text}</span></li>)}</ol></aside></div>
  </section>;
}
