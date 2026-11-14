import { useEffect, useMemo, useState } from 'react';
import { downloadArchive, request } from '../api';
import { Chart, histogramOption } from '../components/Chart';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Icon } from '../components/Icon';
import type { ArchiveDetail, ArchivesPayload, NormalizeParams, ArchivedPaper, ScoreShape } from '../model';

interface Props { revision: number; onToast: (message: string) => void }

function timeText(value: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  return isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function bandText(paper: ArchivedPaper) {
  return paper.band === 'pass' ? '及格组' : paper.band === 'fail' ? '不及格组' : '未评分';
}

const isDemo = (name: string) => name.startsWith('【演示】');
const SHAPE_OPTIONS: { key: ScoreShape; label: string }[] = [
  { key: 'balanced', label: '均衡' }, { key: 'high', label: '高分集中' }, { key: 'low', label: '低分集中' },
];

function presetParams(shape: 'balanced' | 'high' | 'low', intensity: number, threshold: number, decimals: number): NormalizeParams {
  let passMean = 75, passSd = 25, failMean = 50, failSd = 8;
  const factor = intensity / 100;
  if (shape === 'high') { passMean += factor * (100 - 75); passSd += factor * (4 - 25); }
  if (shape === 'low') { failMean += factor * (40 - 50); failSd += factor * (4 - 8); }
  const round = (value: number) => Math.round(value * 100) / 100;
  return { threshold, decimals, shape, intensity, passMean: round(passMean), passSd: round(passSd), failMean: round(failMean), failSd: round(failSd) };
}

function shapeHint(shape: ScoreShape) {
  if (shape === 'high') return '仅及格组向 100±4 靠拢，不及格组保持不变；强度 100% 时均值可达到 100。';
  if (shape === 'low') return '仅不及格组向 40±4 靠拢，及格组保持不变。';
  if (shape === 'custom') return '当前使用手动设定的均值与标准差；修改下方均值或标准差会保持自定义模式。';
  return '保持默认均衡正态分布：及格组 75±25、不及格组 50±8。';
}

export function History({ revision, onToast }: Props) {
  const [payload, setPayload] = useState<ArchivesPayload | null>(null);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<ArchiveDetail | null>(null);
  const [params, setParams] = useState<NormalizeParams | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleteClass, setDeleteClass] = useState(false);
  const [deleteBatch, setDeleteBatch] = useState('');
  const [clearDemo, setClearDemo] = useState(false);
  const demoClasses = (payload?.classes || []).filter(item => isDemo(item.name));

  const load = async (preferred?: string) => {
    try {
      const data = await request<ArchivesPayload>('/archives');
      setPayload(data);
      setSelected(current => preferred || (data.classes.some(item => item.id === current) ? current : data.classes[0]?.id || ''));
      setError('');
    } catch (reason) { setError((reason as Error).message); }
  };

  useEffect(() => { void load(); }, [revision]);

  useEffect(() => {
    if (!selected) { setDetail(null); setParams(null); return; }
    let active = true;
    setLoading(true);
    request<ArchiveDetail>('/archives/classes/' + selected)
      .then(data => {
        if (!active) return;
        setDetail(data);
        setParams({ threshold: data.class.threshold, passMean: data.class.passMean, passSd: data.class.passSd, failMean: data.class.failMean, failSd: data.class.failSd, decimals: data.class.decimals, shape: data.class.shape, intensity: data.class.intensity });
        setError('');
      })
      .catch(reason => { if (active) setError((reason as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [selected, revision]);

  const rawOption = useMemo(() => histogramOption(detail?.stats.rawBins || [0, 0, 0, 0, 0]), [detail]);
  const adjustedOption = useMemo(() => histogramOption(detail?.stats.adjustedBins || [0, 0, 0, 0, 0]), [detail]);
  const number = (value: number | null, digits = 1) => value === null || value === undefined ? '—' : value.toFixed(digits);

  const apply = async () => {
    if (!selected || !params) return;
    setSaving(true);
    try {
      const data = await request<ArchiveDetail>('/archives/classes/' + selected + '/normalize', params);
      setDetail(data);
      setParams({ threshold: data.class.threshold, passMean: data.class.passMean, passSd: data.class.passSd, failMean: data.class.failMean, failSd: data.class.failSd, decimals: data.class.decimals, shape: data.class.shape, intensity: data.class.intensity });
      onToast('已按新的正态参数重新赋分。');
      await load(selected);
    } catch (reason) { setError((reason as Error).message); }
    finally { setSaving(false); }
  };

  const exportClass = async () => {
    if (!detail) return;
    try { await downloadArchive(detail.class.id, detail.class.name); onToast('班级成绩存档已导出。'); }
    catch (reason) { onToast((reason as Error).message); }
  };

  const removeClass = async () => {
    if (!selected) return;
    try {
      await request('/archives/classes/' + selected, undefined, 'DELETE');
      setDeleteClass(false); setDetail(null); onToast('班级存档已删除。'); await load();
    } catch (reason) { onToast((reason as Error).message); }
  };

  const removeBatch = async (id: string) => {
    try {
      await request('/archives/batches/' + id, undefined, 'DELETE');
      setDeleteBatch(''); onToast('批次已删除，班级成绩已重新赋分。');
      const data = await request<ArchiveDetail>('/archives/classes/' + selected);
      setDetail(data);
      await load(selected);
    } catch (reason) { onToast((reason as Error).message); }
  };

  const chooseShape = (shape: ScoreShape) => setParams(current => !current ? current
    : shape === 'custom' ? { ...current, shape }
    : presetParams(shape, current.intensity, current.threshold, current.decimals));
  const setIntensity = (value: number) => setParams(current => {
    if (!current) return current;
    return current.shape === 'high' || current.shape === 'low'
      ? presetParams(current.shape, value, current.threshold, current.decimals)
      : { ...current, intensity: value };
  });
  const update = (key: 'threshold' | 'passMean' | 'passSd' | 'failMean' | 'failSd' | 'decimals', value: number) => setParams(current => {
    if (!current) return current;
    const shape = key === 'passMean' || key === 'passSd' || key === 'failMean' || key === 'failSd' ? 'custom' : current.shape;
    return { ...current, [key]: value, shape } as NormalizeParams;
  });

  const clearDemoArchives = async () => {
    const targets = (payload?.classes || []).filter(item => isDemo(item.name));
    try {
      for (const item of targets) await request('/archives/classes/' + item.id, undefined, 'DELETE');
      setClearDemo(false); setDetail(null);
      onToast(`已清除 ${targets.length} 个演示班级存档。`);
      await load();
    } catch (reason) { onToast((reason as Error).message); }
  };

  return <main className="editorial-page animate-page-in">
    <div className="page-heading"><h1 className="font-serif text-page-title">历史存档</h1><div className="flex items-center gap-6"><span className="text-caption text-muted">按班级保存成绩 · 及格/不及格分组 · 正态赋分</span>{!!demoClasses.length && <button className="quiet-link text-accent" onClick={() => setClearDemo(true)}>清除演示存档</button>}</div></div>
    {error && <div className="configuration-note" role="alert"><span>{error}</span><button className="quiet-link" onClick={() => void load(selected)}>重新加载</button></div>}
    <div className="history-layout">
      <aside className="review-directory" aria-label="班级存档目录">
        <div className="directory-heading"><h2 className="font-serif text-section-title">班级目录</h2><span>{payload?.classes.length || 0} 个班级</span></div>
        {payload?.classes.length ? <ol>{payload.classes.map((item, index) => <li key={item.id}>
          <button className={`directory-row ${selected === item.id ? 'is-active' : ''}`} aria-current={selected === item.id ? 'page' : undefined} onClick={() => setSelected(item.id)}>
            <span className="directory-index font-serif">{String(index + 1).padStart(2, '0')}</span>
            <span className="min-w-0 flex-1"><strong>{item.name}{isDemo(item.name) && <em className="demo-badge">演示</em>}</strong><span className="directory-title">{item.course || '未填写课程'} · {item.paperCount} 篇 · 及格率 {item.passRate === null ? '—' : item.passRate.toFixed(0) + '%'}</span></span>
            <span className="font-serif directory-score">{number(item.adjustedMean)}</span>
          </button>
        </li>)}</ol> : <div className="empty-state"><p className="font-serif text-section-title">还没有班级存档</p><p className="text-caption text-muted mt-3">先在批量评阅页完成评阅，再用“归档本批”保存到班级。</p></div>}
      </aside>
      <section className="reading-article">
        {!detail ? <div className="empty-state"><p role="status" className="text-caption text-muted">{loading ? '正在读取班级存档…' : '从左侧选择一个班级查看成绩'}</p></div> :
          <article aria-label={`${detail.class.name}的成绩存档`}>
            <div className="article-masthead"><span>{detail.class.course || '未填写课程'}<span className="mx-3 text-hairline">/</span>{detail.class.paperCount} 篇论文<span className="mx-3 text-hairline">/</span>{detail.batches.length} 个批次</span><span>最近归档 · {timeText(detail.class.lastArchivedAt)}</span></div>
            {isDemo(detail.class.name) && <p className="demo-note" role="note">演示存档：数据为人工构造，仅用于检验分组与赋分效果；可在页面右上角“清除演示存档”一键删除。</p>}
            <div className="article-heading"><h2 className="font-serif">{detail.class.name}</h2><div className="article-score"><strong className="font-serif">{number(detail.stats.adjustedMean)}</strong><span>班级赋分均分</span></div></div>
            <div className="summary-line archive-summary">
              <span>原始均分 <strong className="font-serif">{number(detail.stats.rawMean)}</strong></span>
              <span>赋分标准差 <strong className="font-serif">{number(detail.stats.adjustedSd)}</strong></span>
              <span>及格组 <strong className="font-serif">{detail.class.passCount}</strong> 篇</span>
              <span>不及格组 <strong className="font-serif">{detail.class.failCount}</strong> 篇</span>
              <span>及格率 <strong className="font-serif">{detail.stats.passRate === null ? '—' : detail.stats.passRate.toFixed(0) + '%'}</strong></span>
            </div>
            <div className="archive-charts">
              <div className="chart-section"><div className="chart-heading"><h3 className="font-serif text-lg">原始分分布</h3><span>篇数 / 分数段</span></div><Chart option={rawOption} label="班级原始总分分布" className="h-[195px]" /></div>
              <div className="chart-section"><div className="chart-heading"><h3 className="font-serif text-lg">赋分后分布</h3><span>篇数 / 分数段</span></div><Chart option={adjustedOption} label="正态赋分后的班级分数分布" className="h-[195px]" /></div>
            </div>
            {params && <section className="archive-params" aria-label="正态赋分参数">
              <div className="archive-params-heading"><h3 className="font-serif text-section-title">正态赋分参数</h3><p className="text-caption text-muted">组内按原始分排名映射到截断正态分布；同分同分，顺序不变。</p></div>
              <div className="archive-shape-block">
                <div className="archive-shape-tabs" role="group" aria-label="赋分形态">
                  {SHAPE_OPTIONS.map(item => <button key={item.key} className={`archive-shape-button ${params.shape === item.key ? 'is-active' : ''}`} aria-pressed={params.shape === item.key} disabled={saving} onClick={() => chooseShape(item.key)}>{item.label}</button>)}
                  {params.shape === 'custom' && <span className="archive-shape-current">自定义</span>}
                </div>
                {(params.shape === 'high' || params.shape === 'low') && <div className="archive-intensity">
                  <label htmlFor="archive-intensity">集中强度</label>
                  <input id="archive-intensity" className="archive-intensity-range" type="range" min={0} max={100} step={5} value={params.intensity} onChange={event => setIntensity(Number(event.target.value))} disabled={saving} />
                  <strong className="font-serif">{params.intensity}%</strong>
                </div>}
                <p className="archive-shape-hint">{shapeHint(params.shape)}</p>
              </div>
              <div className="archive-param-grid">
                <label><span>及格线</span><input className="editorial-input" type="number" min={0} max={100} step={1} value={params.threshold} onChange={event => update('threshold', Number(event.target.value))} /></label>
                <label><span>及格组均值</span><input className="editorial-input" type="number" min={0} max={100} step={0.1} value={params.passMean} onChange={event => update('passMean', Number(event.target.value))} /></label>
                <label><span>及格组标准差</span><input className="editorial-input" type="number" min={0.1} max={30} step={0.1} value={params.passSd} onChange={event => update('passSd', Number(event.target.value))} /></label>
                <label><span>不及格组均值</span><input className="editorial-input" type="number" min={0} max={100} step={0.1} value={params.failMean} onChange={event => update('failMean', Number(event.target.value))} /></label>
                <label><span>不及格组标准差</span><input className="editorial-input" type="number" min={0.1} max={30} step={0.1} value={params.failSd} onChange={event => update('failSd', Number(event.target.value))} /></label>
                <label><span>保留小数</span><select className="editorial-input" value={params.decimals} onChange={event => update('decimals', Number(event.target.value))}><option value={0}>0 位</option><option value={1}>1 位</option><option value={2}>2 位</option></select></label>
              </div>
              <div className="archive-param-actions"><button className="text-action" disabled={saving} onClick={() => void apply()}>{saving ? '正在重新赋分…' : '应用并重新赋分'}<Icon name="check" size={16} /></button><span className="text-caption text-muted">调整后全班重新计算，分组仍以原始总分为准。</span></div>
            </section>}
            <table className="archive-table" aria-label="班级成绩表">
              <thead><tr><th>序号</th><th>论文</th><th>原始分</th><th>分组</th><th>正态赋分</th><th>复核</th></tr></thead>
              <tbody>{detail.papers.map((paper, index) => <tr key={paper.id}>
                <td className="font-serif">{String(index + 1).padStart(2, '0')}</td>
                <td><strong>{paper.title}</strong><span className="paper-file">{paper.name}</span></td>
                <td className="font-serif">{paper.rawTotal === null ? '—' : paper.rawTotal.toFixed(1)}</td>
                <td><span className={`archive-band ${paper.band || 'none'}`}>{bandText(paper)}</span></td>
                <td className="font-serif archive-adjusted">{paper.adjustedTotal === null ? '—' : paper.adjustedTotal.toFixed(detail.class.decimals)}</td>
                <td className="text-caption text-muted">{paper.reviewed ? '教师已确认' : '未确认'}</td>
              </tr>)}</tbody>
            </table>
            <section className="archive-batches" aria-label="归档批次">
              <div className="directory-heading"><h3 className="font-serif text-section-title">归档批次</h3><span>{detail.batches.length} 批</span></div>
              <ol>{detail.batches.map((batch, index) => <li key={batch.id}>
                <span className="font-serif">{String(index + 1).padStart(2, '0')}</span>
                <div><strong>{timeText(batch.createdAt)}</strong><span>{batch.paperCount} 篇{batch.rubricName ? ' · ' + batch.rubricName : ''}</span></div>
                <button className="quiet-link text-accent" onClick={() => setDeleteBatch(batch.id)}>删除批次</button>
              </li>)}</ol>
            </section>
            <footer className="reading-footer"><button className="text-action" onClick={() => void exportClass()}>导出班级成绩<Icon name="download" size={18} /></button><button className="quiet-link text-accent" onClick={() => setDeleteClass(true)}>删除班级存档</button></footer>
          </article>}
      </section>
    </div>
    <ConfirmDialog open={deleteClass} title="删除班级存档" description={`将永久删除“${detail?.class.name || ''}”的全部论文成绩与报告存档，无法恢复。`} confirmText="确认删除"
      onCancel={() => setDeleteClass(false)} onConfirm={() => void removeClass()} />
    <ConfirmDialog open={!!deleteBatch} title="删除归档批次" description="仅删除这一批论文的成绩，随后按剩余论文重新赋分。" confirmText="确认删除"
      onCancel={() => setDeleteBatch('')} onConfirm={() => void removeBatch(deleteBatch)} />
    <ConfirmDialog open={clearDemo} title="清除演示存档" description={`将删除 ${demoClasses.length} 个以“【演示】”开头的班级及其全部论文与报告，不影响其他班级。`} confirmText="确认清除"
      onCancel={() => setClearDemo(false)} onConfirm={() => void clearDemoArchives()} />
  </main>;
}
