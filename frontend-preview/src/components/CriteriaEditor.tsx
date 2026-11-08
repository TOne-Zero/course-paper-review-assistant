import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Chart, weightOption } from './Chart';
import { ConfirmDialog } from './ConfirmDialog';
import { Icon } from './Icon';

export interface Dimension { id: string; name: string; weight: number; detailText: string; detailScores?: number[]; }
export interface CriteriaStandard { id: string; name: string; dimensions: Dimension[]; }
interface DetailItem { id: number; text: string; score: string; }
interface DraftDimension { id: string; name: string; weight: string; items: DetailItem[]; }
let nextDetailId = 0;
export const splitDetails = (text: string) => text.split(/[;；\r\n]+/).map(item => item.trim()).filter(Boolean);
const distribute = (total: number, count: number) => {
  const cents = Math.round(total * 100), each = Math.floor(cents / count);
  return Array.from({ length: count }, (_, index) => (each + (index === count - 1 ? cents - each * count : 0)) / 100);
};
const toDraft = (standard: CriteriaStandard): DraftDimension[] => standard.dimensions.map(dimension => ({
  id: dimension.id, name: dimension.name, weight: String(dimension.weight),
  items: (splitDetails(dimension.detailText).length ? splitDetails(dimension.detailText) : ['']).map((text, index, items) => ({
    id: ++nextDetailId, text, score: String(dimension.detailScores?.[index] ?? distribute(dimension.weight, items.length)[index]),
  })),
}));
const fingerprint = (dimensions: DraftDimension[]) => JSON.stringify(dimensions.map(dimension => ({
  id: dimension.id, weight: dimension.weight, items: dimension.items.map(item => ({ text: item.text, score: item.score })),
})));
const itemTotal = (dimension: DraftDimension) => Math.round(dimension.items.reduce((sum, item) => sum + (Number(item.score) || 0), 0) * 100) / 100;
const twoDecimals = (value: number) => Number.isFinite(value) && Math.abs(value * 100 - Math.round(value * 100)) < 1e-7;
const validItemScores = (dimension: DraftDimension) => dimension.items.every(item => item.score.trim() !== '' && twoDecimals(Number(item.score)) && Number(item.score) >= 0 && Number(item.score) <= Number(dimension.weight)) && Math.abs(itemTotal(dimension) - Number(dimension.weight)) < .001;

function DetailInput({ value, label, inputId, disabled, onChange, onSplit }: {
  value: string; label: string; inputId: string; onChange: (value: string) => void; onSplit: () => void;
  disabled: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const input = ref.current;
    if (!input) return;
    const resize = () => { input.style.height = '0px'; input.style.height = `${input.scrollHeight}px`; };
    resize();
    const observer = new ResizeObserver(resize); observer.observe(input.parentElement!);
    return () => observer.disconnect();
  }, [value]);
  return <textarea ref={ref} id={inputId} aria-label={label} rows={1} maxLength={4000} disabled={disabled}
    className="criteria-detail-input" value={value} onChange={event => onChange(event.target.value)} onBlur={onSplit}
    placeholder="写下需要检查的内容" />;
}

export function CriteriaEditor({ standards, initialId, savedValues = {}, versions = {}, preview = true, appliedId, disabled = false, onSave, onDirtyChange, onStandardChange, onSavingChange }: {
  standards: CriteriaStandard[]; initialId: string;
  savedValues?: Record<string, Dimension[]>;
  versions?: Record<string, string>; preview?: boolean; appliedId?: string; disabled?: boolean;
  onSavingChange?: (saving: boolean) => void;
  onStandardChange?: (id: string) => void;
  onSave: (id: string, dimensions: Dimension[], version?: string) => Promise<string | void>; onDirtyChange: (dirty: boolean) => void;
}) {
  const [activeId, setActiveId] = useState(initialId);
  const [draft, setDraft] = useState(() => { const standard = standards.find(item => item.id === initialId) || standards[0];
    return toDraft({ ...standard, dimensions: savedValues[standard.id] || standard.dimensions }); });
  const [baseline, setBaseline] = useState(() => fingerprint(draft));
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pendingTab, setPendingTab] = useState<string | null>(null);
  const [confirmSave, setConfirmSave] = useState(false), [saving, setSaving] = useState(false);
  const [error, setError] = useState(''), [saved, setSaved] = useState(false);
  const [editVersion, setEditVersion] = useState(versions[initialId]);
  const active = standards.find(item => item.id === activeId)!;
  const hasSaved = preview ? !!savedValues[activeId] : versions[activeId]?.startsWith('web-');
  const dirty = fingerprint(draft) !== baseline;
  const weights = draft.map(item => Number(item.weight) || 0);
  const total = Math.round(weights.reduce((sum, weight) => sum + weight, 0) * 100) / 100;
  const validWeights = draft.every(item => item.weight.trim() !== '' && twoDecimals(Number(item.weight)) && Number(item.weight) > 0 && Number(item.weight) <= 100);
  const validDetails = draft.every(item => item.items.length > 0 && item.items.length <= 50 && item.items.every(detail => detail.text.trim() !== '') && item.items.map(detail => detail.text.trim()).join('；').length <= 4000);
  const validScores = draft.every(validItemScores);
  const weightKey = weights.join(','), nameKey = draft.map(item => item.name).join(',');
  const ring = useMemo(() => weightOption(weights, draft.map(item => item.name), 1), [weightKey, nameKey]);
  useEffect(() => { onDirtyChange(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onSavingChange?.(saving); }, [saving, onSavingChange]);
  useEffect(() => {
    if (!dirty && !saving && versions[activeId] !== editVersion) {
      const standard = standards.find(item => item.id === activeId)!;
      const values = toDraft({ ...standard, dimensions: savedValues[activeId] || standard.dimensions });
      setDraft(values); setBaseline(fingerprint(values)); setEditVersion(versions[activeId]);
    }
  }, [versions[activeId], dirty, saving, activeId]);
  useEffect(() => { onStandardChange?.(activeId); }, [activeId, onStandardChange]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    addEventListener('beforeunload', prevent); return () => removeEventListener('beforeunload', prevent);
  }, [dirty]);
  const update = (id: string, change: (value: DraftDimension) => DraftDimension) => {
    setSaved(false); setError(''); setDraft(values => values.map(value => value.id === id ? change(value) : value));
  };
  const switchTab = (id: string) => {
    const standard = standards.find(item => item.id === id)!;
    const values = toDraft({ ...standard, dimensions: savedValues[id] || standard.dimensions });
    setActiveId(id); setDraft(values); setBaseline(fingerprint(values)); setExpanded(null); setError(''); setSaved(false);
    setEditVersion(versions[id]);
  };
  const save = async () => {
    setConfirmSave(false); setSaving(true); setError('');
    const dimensions: Dimension[] = draft.map(item => ({ id: item.id, name: item.name, weight: Number(item.weight),
      detailText: item.items.flatMap(detail => splitDetails(detail.text)).join('；'),
      detailScores: item.items.flatMap(detail => distribute(Number(detail.score), Math.max(1, splitDetails(detail.text).length))),
    }));
    try {
      const version = await onSave(activeId, dimensions, editVersion);
      if (version) setEditVersion(version);
      const values = toDraft({ ...active, dimensions }); setDraft(values); setBaseline(fingerprint(values)); setSaved(true);
    } catch (reason) { setError((reason as Error).message || '未保存成功，请重试。'); }
    finally { setSaving(false); }
  };
  const selectTab = (index: number) => {
    const id = standards[(index + standards.length) % standards.length].id;
    if (id !== activeId) { if (dirty) setPendingTab(id); else switchTab(id); }
    document.getElementById(`criteria-tab-${id}`)?.focus();
  };
  return <section className="criteria-editor">
    <div className="criteria-heading"><div><h3 className="font-serif text-section-title">评分标准</h3>
      <p className="criteria-intro">展开维度，编辑细则与各条分值。</p></div>
      <span className={`criteria-save-status ${dirty ? 'is-dirty' : ''}`} role="status">{dirty ? '未保存' : saved || hasSaved ? preview ? '已保存到预览' : '已保存到本机' : '默认预设'}</span>
    </div>
    <div className="criteria-tabs" role="tablist" aria-label="论文评分标准">
      {standards.map((standard, index) => <button key={standard.id} id={`criteria-tab-${standard.id}`} role="tab"
        aria-selected={activeId === standard.id} aria-controls="criteria-tab-panel" tabIndex={activeId === standard.id ? 0 : -1}
        disabled={saving} onClick={() => { if (standard.id !== activeId) { if (dirty) setPendingTab(standard.id); else switchTab(standard.id); } }}
        onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          event.preventDefault(); selectTab(event.key === 'Home' ? 0 : event.key === 'End' ? standards.length - 1 : index + (event.key === 'ArrowRight' ? 1 : -1));
        } }}>
        {standard.name}
      </button>)}
    </div>
    <fieldset disabled={saving || disabled} className="criteria-fieldset"><div id="criteria-tab-panel" role="tabpanel" aria-labelledby={`criteria-tab-${activeId}`}>
      <div className="criteria-overview"><span>{draft.length} 个维度{!preview && (appliedId === activeId ? ' · 当前使用' : ' · 保存后使用')}</span><span>满分 100 分</span></div>
      <div className="criteria-layout">
        <div className="criteria-dimensions">
          <div className="criteria-column-labels"><span>评价维度 / 检查细则</span><span>分值</span></div>
          {draft.map(dimension => {
            const isOpen = expanded === dimension.id;
            const preset = active.dimensions.find(item => item.id === dimension.id)!;
            const panelId = `detail-panel-${activeId}-${dimension.id}`;
            return <div key={dimension.id} className={`criteria-dimension ${isOpen ? 'is-expanded' : ''}`}>
              <div className="criteria-dimension-row">
                <button id={`${panelId}-trigger`} className="criteria-dimension-toggle" disabled={saving} aria-expanded={isOpen} aria-controls={panelId}
                  onClick={() => setExpanded(isOpen ? null : dimension.id)}>
                  <Icon name="chevron" size={15} /><span>{dimension.name}</span>
                  <small className={!validItemScores(dimension) ? 'text-accent' : ''}>{validItemScores(dimension) ? `${dimension.items.length} 条` : '分值待调整'}</small>
                </button>
                <label className="criteria-weight-field"><span className="sr-only">{dimension.name}权重</span>
                  <input aria-label={`${dimension.name}权重`} type="number" min={0.01} max={100} step={0.01} className="weight-input" value={dimension.weight} disabled={saving}
                    onChange={event => update(dimension.id, value => ({ ...value, weight: event.target.value }))} /><span>分</span>
                </label>
              </div>
              <div id={panelId} className="criteria-accordion" {...(!isOpen ? { inert: '' } : {})} aria-hidden={!isOpen}>
                <div className="criteria-accordion-inner"><div className="criteria-detail-panel" role="region" aria-labelledby={`${panelId}-trigger`}>
                  <div className="criteria-detail-column-labels"><span>检查细则</span><span>分值</span></div>
                  <div className="criteria-detail-list">
                    {dimension.items.map((item, index) => <div className="criteria-detail-row" key={item.id}>
                      <span className="criteria-detail-number" aria-hidden="true">{index + 1}</span>
                      <DetailInput inputId={`detail-${item.id}`} label={`${dimension.name}细则 ${index + 1}`} value={item.text} disabled={saving}
                        onChange={text => update(dimension.id, value => ({ ...value, items: value.items.map(detail => detail.id === item.id ? { ...detail, text } : detail) }))}
                        onSplit={() => {
                          const parts = splitDetails(item.text);
                          if (parts.length > 1) update(dimension.id, value => ({ ...value, items: value.items.flatMap(detail => detail.id === item.id ? parts.map((text, i) => ({ id: ++nextDetailId, text, score: String(distribute(Number(item.score) || 0, parts.length)[i]) })) : [detail]) }));
                        }} />
                      <label className="criteria-detail-score"><span className="sr-only">{dimension.name}细则 {index + 1}分值</span>
                        <input aria-label={`${dimension.name}细则 ${index + 1}分值`} className="weight-input" type="number" min={0} max={Number(dimension.weight) || 100} step={0.01}
                          value={item.score} disabled={saving} onChange={event => update(dimension.id, value => ({ ...value, items: value.items.map(detail => detail.id === item.id ? { ...detail, score: event.target.value } : detail) }))} />
                        <span>分</span>
                      </label>
                      <button className="icon-button criteria-remove" disabled={saving || dimension.items.length === 1} aria-label={`删除${dimension.name}细则 ${index + 1}`}
                        onClick={() => update(dimension.id, value => ({ ...value, items: value.items.filter(detail => detail.id !== item.id) }))}><Icon name="close" size={15} /></button>
                    </div>)}
                  </div>
                  <div className={`criteria-subtotal ${!validItemScores(dimension) ? 'is-invalid' : ''}`}>
                    <span aria-live="polite">小项合计 <strong>{itemTotal(dimension)}</strong> / {dimension.weight || '—'} 分</span>
                    <button className="quiet-link" disabled={saving || !(Number(dimension.weight) > 0)} onClick={() => update(dimension.id, value => ({ ...value,
                      items: value.items.map((detail, i) => ({ ...detail, score: String(distribute(Number(value.weight), value.items.length)[i]) })),
                    }))}>均分分值</button>
                  </div>
                  {!validItemScores(dimension) && <p role="alert" className="criteria-score-error">分值最多两位小数，合计须为本维度的 {dimension.weight || '—'} 分。</p>}
                  <p className="criteria-short-hint">初始分值按维度均分，可逐条调整。</p>
                  {splitDetails(preset.detailText).length === 1 && <p className="criteria-short-hint">本维度预设较简略，您可直接补充细节。</p>}
                  <div className="criteria-detail-actions">
                    <button className="quiet-link" disabled={saving || dimension.items.length >= 50} onClick={() => {
                      const id = ++nextDetailId;
                      update(dimension.id, value => ({ ...value, items: [...value.items, { id, text: '', score: '0' }] }));
                      requestAnimationFrame(() => document.getElementById(`detail-${id}`)?.focus());
                    }}><Icon name="plus" size={15} />添加一条细则</button>
                    <button className="quiet-link criteria-reset" disabled={saving} onClick={() => update(dimension.id, () => toDraft({ ...active, dimensions: [preset] })[0])}>
                      <Icon name="reset" size={14} />恢复该维度默认预设
                    </button>
                  </div>
                </div></div>
              </div>
            </div>;
          })}
        </div>
        <aside className="criteria-weight-summary" aria-label="权重分布">
          <div className="weight-figure"><Chart option={ring} label={`${draft.length}维度权重分布，合计${total}分`} className="h-[166px] w-[166px] max-w-full" />
            <div className={`weight-total ${total !== 100 ? 'text-accent' : ''}`}><strong className="font-serif">{total}</strong><span>总分 / 100</span></div>
          </div><p>权重实时联动</p>
        </aside>
      </div>
      <div className="criteria-footer">
        <p className="criteria-warning">修改评分条件后，已有评分与复核将清除，需重新评阅。</p>
        {(!validWeights || total !== 100) && <p className="form-error" role="alert">各维度分值须大于 0，合计须为 100 分；当前为 {total} 分。</p>}
        {!validDetails && <p className="form-error" role="alert">请补全细则，每个维度保留 1–50 条、合计不超过 4000 字。</p>}
        {!validScores && <p className="form-error" role="alert">小项分值合计须与所属维度一致，请展开对应维度调整。</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {disabled && <p className="form-error" role="status">评阅进行中，请暂停并等待当前篇完成后修改。</p>}
        {saved && <p className="criteria-preview-saved" role="status">{preview ? '已保存到本次预览，正式评分未变更。' : '评分标准已保存，后续评阅将采用这些细则与分值。'}</p>}
        <div className="criteria-footer-actions"><button className="text-action" disabled={(!dirty && (preview || appliedId === activeId)) || saving || !validWeights || total !== 100 || !validDetails || !validScores}
          onClick={() => setConfirmSave(true)}>{saving ? '正在保存…' : '保存评分标准'}<Icon name="arrow" size={18} /></button>
          <span className="text-caption text-muted">{preview ? '前端预览 · 不影响正式数据' : '保存到本机 · 刷新后保留'}</span></div>
      </div>
    </div></fieldset>
    <ConfirmDialog open={pendingTab !== null} title="放弃未保存的修改？" description="存在未保存的修改，是否确认放弃？" confirmText="确认放弃"
      onCancel={() => setPendingTab(null)} onConfirm={() => { if (pendingTab) switchTab(pendingTab); setPendingTab(null); }} />
    <ConfirmDialog open={confirmSave} title="确认修改评分标准" description="警告：修改评分条件后，已有评分与复核将被清除，需重新评阅。是否确认修改？" confirmText="确认修改"
      onCancel={() => setConfirmSave(false)} onConfirm={() => void save()} />
  </section>;
}
