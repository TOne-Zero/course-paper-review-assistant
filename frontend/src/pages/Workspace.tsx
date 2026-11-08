import { useMemo, useRef, useState } from 'react';
import { Chart, histogramOption, radarOption } from '../components/Chart';
import { Icon } from '../components/Icon';
import { batchSummary, hasScore, hasResult, paperScore, STATUS_CLASS, STATUS_TEXT, type Paper, type Rubric } from '../model';

interface Props {
  papers: Paper[]; weights: number[]; dimensions:string[]; criteria: string; rubrics:Rubric[]; running: boolean; busy:boolean; simulation:boolean; progress:string; consent:boolean; onConsent:(value:boolean)=>void;
  configured: boolean; onSettings: () => void; onCriteria: (value: string) => void;
  onFiles: (files: File[]) => void; onRemove: (id: string) => void;
  onSelect: (id: string) => void; onStart: () => void; onDemo: () => void; onExport: () => void;
}

export function Workspace(props: Props) {
  const { papers, weights, criteria, running } = props;
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const summary = useMemo(() => batchSummary(papers, weights), [papers, weights]);
  const histogram = useMemo(() => histogramOption(summary.bins), [summary]);
  const radar = useMemo(() => radarOption(summary.means,false,props.dimensions), [summary,props.dimensions]);
  return <main className="editorial-page animate-page-in">
    {!props.simulation&&!props.configured && <div className="configuration-note"><span>正式评阅前，请先配置模型服务。</span><button className="quiet-link" onClick={props.onSettings}>前往设置 <Icon name="arrow" size={16} /></button></div>}
    <div className="page-heading"><h1 className="font-serif text-page-title">批量评阅</h1><span className="text-caption text-muted">{props.simulation?'模拟运行 · 不调用模型':'当前批次'}</span></div>
    {!props.simulation&&!!papers.length&&<label className="flex items-start gap-3 mb-6 text-caption text-muted"><input type="checkbox" className="mt-1 accent-accent" checked={props.consent} disabled={running} onChange={e=>props.onConsent(e.target.checked)}/>同意将本批论文文本发送至已配置的模型服务</label>}
    {props.progress&&<p role="status" className="text-caption text-muted mb-5">{props.progress}</p>}
    <div className="workspace-grid">
      <section className="min-w-0" aria-labelledby="papers-heading">
        <div className="section-heading"><h2 id="papers-heading" className="font-serif text-section-title">论文目录</h2><span className="text-caption text-muted">{papers.length} / 10 篇</span></div>
        <div className="progress-meta"><span>{summary.processed} 篇已评阅</span><button className="quiet-link" onClick={props.onStart} disabled={props.busy||!papers.length}>{running ? '暂停后续' : '开始评阅'} <Icon name={running ? 'pause' : 'arrow'} size={15} /></button></div>
        <div className="batch-progress" role="progressbar" aria-label="批次评阅进度" aria-valuemin={0} aria-valuemax={papers.length || 10} aria-valuenow={summary.processed}><span style={{ width: `${papers.length ? summary.processed / papers.length * 100 : 0}%` }} /></div>
        <div className={`upload-frame ${dragging ? 'is-dragging' : ''}`}
          onDragOver={event => { event.preventDefault(); setDragging(true); }}
          onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }}
          onDrop={event => { event.preventDefault(); setDragging(false); props.onFiles(Array.from(event.dataTransfer.files)); }}>
          {['crop-mark-0', 'crop-mark-1', 'crop-mark-2', 'crop-mark-3'].map(corner => <span key={corner} className={`crop-mark ${corner}`} aria-hidden="true" />)}
          <button className="upload-choice" disabled={props.busy||running} onClick={() => input.current?.click()}><Icon name="plus" size={21} /><span>{props.busy?'正在处理…':'拖入 Word / PDF，或点击选择'}</span><small>每批至多 10 篇 · 合计 50 MB</small></button>
          <input ref={input} className="hidden" type="file" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" multiple aria-label="批量上传论文"
            onChange={event => { props.onFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
        </div>
        {papers.length ? <ol className="paper-list" aria-label="当前批次论文">
          {papers.map(paper => <li key={paper.id} className="paper-row">
            <button className="paper-row-main" onClick={() => props.onSelect(paper.id)} aria-label={`打开 ${paper.student} 的论文：${paper.title}`}>
              <span className={paper.status === 'processing' ? 'paper-spinner status-processing' : `status-dot ${STATUS_CLASS[paper.status]}`} title={STATUS_TEXT[paper.status]} aria-label={STATUS_TEXT[paper.status]} />
              <span className="min-w-0 flex-1"><span className="paper-filename" title={paper.name}>{paper.name}</span><span className={`paper-meta ${paper.status === 'review' || paper.status === 'failed' ? 'text-accent' : 'text-muted'}`}>{paper.student} <span aria-hidden="true">·</span> {paper.reviewed ? '已复核' : paper.report&&paper.totalScore===null?'部分缺分 · 待复核':STATUS_TEXT[paper.status]}</span></span>
              <span className="paper-score font-serif">{hasScore(paper) ? paperScore(paper, weights).toFixed(1) : '—'}</span>
            </button>
            <button className="paper-remove icon-button" disabled={props.busy||running} onClick={() => props.onRemove(paper.id)} aria-label={`移除 ${paper.name}`}><Icon name="close" size={15} /></button>
          </li>)}
        </ol> : <div className="empty-state"><p className="font-serif text-section-title">等待第一篇论文</p>{props.simulation&&<button className="quiet-link mt-3" disabled={props.busy} onClick={props.onDemo}>载入示例论文 <Icon name="arrow" size={16} /></button>}</div>}
      </section>
      <aside className="overview-panel" aria-labelledby="overview-heading">
        <div className="section-heading"><h2 id="overview-heading" className="font-serif text-section-title">评阅概况</h2><span className="text-caption text-muted">共用评分标准</span></div>
        <label className="field-label" htmlFor="criteria">当前标准</label>
        <div className="select-wrap"><select id="criteria" value={criteria} disabled={props.busy||running} onChange={event => props.onCriteria(event.target.value)} className="editorial-input appearance-none pr-10">{props.rubrics.map(r=><option value={r.id} key={r.id}>{r.name}</option>)}</select><Icon name="chevron" size={16} /></div>
        <div className="summary-line"><span>已评阅 <span className="font-serif text-lg text-ink">{summary.count}</span> 篇</span><span>批次均分 <span className="font-serif text-2xl text-ink">{summary.mean === null ? '—' : summary.mean.toFixed(1)}</span></span><span>待复核 <span className="font-serif text-lg text-ink">{summary.pendingReview}</span> 篇</span></div>
        <div className="chart-section"><div className="chart-heading"><h3 className="font-serif text-lg">分数分布</h3><span>篇数 / 分数段</span></div>
          {summary.count ? <Chart option={histogram} label={`分数分布，共${summary.count}篇，依次为${summary.bins.join('、')}篇`} className="h-[195px]" /> : <div className="chart-empty">完成评阅后显示分数分布</div>}
        </div>
        <div className="chart-section"><div className="chart-heading"><h3 className="font-serif text-lg">{props.dimensions.length}维度平均表现</h3><span>各维度得分率 / %</span></div>
          {summary.count ? <Chart option={radar} label="当前批次各维度平均得分率，满分100%" className="h-[290px]" /> : <div className="chart-empty">完成评阅后显示维度表现</div>}
        </div>
        <p className="text-caption text-muted pt-3">图表仅统计已有评分的论文。</p>
      </aside>
    </div>
    <footer className="workspace-footer"><button className="text-action" onClick={props.onExport} disabled={!papers.some(hasResult)}>导出全部报告 <Icon name="download" size={18} /></button><span className="text-caption text-muted">图表仅统计总分完整的论文；AI辅助评价，最终成绩由教师确定</span></footer>
  </main>;
}
