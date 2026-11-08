import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { Chart, weightOption } from './Chart';
import { Icon } from './Icon';
import { ConfirmDialog } from './ConfirmDialog';
import { formatBytes, type ModelSettings, type ModelTestResult, type SettingsSection, type Provider } from '../model';

interface Props {
  criteriaContent?: React.ReactNode; hasUnsavedChanges?: boolean; onDiscardChanges?: () => void; criteriaSaving?: boolean;
  open: boolean; onOpenChange: (open: boolean) => void;
  section: SettingsSection; onSection: (section: SettingsSection) => void;
  model: ModelSettings; weights: number[]; dimensions:string[]; providers:Provider[]; bytes: number; paperCount: number;
  onModel: (model: ModelSettings) => Promise<void>; onWeights: (weights: number[]) => Promise<void>; onClear: () => Promise<void>; onTest:(model:ModelSettings)=>Promise<ModelTestResult>;
}
const sections: { key: SettingsSection; title: string }[] = [{ key: 'model', title: 'AI 模型配置' }, { key: 'criteria', title: '评分标准' }, { key: 'data', title: '数据管理' }];

export function SettingsDrawer(props: Props) {
  const [draft, setDraft] = useState<ModelSettings>({ provider: '自定义', url: '', model: '', key: '', configured: false });
  const [showKey, setShowKey] = useState(false);
  const [weights, setWeights] = useState([...props.weights]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestResult | null>(null);
  const [testError, setTestError] = useState('');
  const [error, setError] = useState('');
  const [confirmClear, setConfirmClear] = useState(false);
  const [saving,setSaving]=useState(false);
  const sameEndpoint = draft.url.trim().replace(/\/$/, '') === props.model.url.replace(/\/$/, '');
  const keyStored = !!(props.model.keySaved || props.model.configured) && sameEndpoint;
  const [pendingNavigation, setPendingNavigation] = useState<SettingsSection | 'close' | null>(null);
  const navigate = (target: SettingsSection | 'close') => {
    if (props.criteriaSaving || saving || testing) return;
    if (props.hasUnsavedChanges) { setPendingNavigation(target); return; }
    if (target === 'close') props.onOpenChange(false); else props.onSection(target);
    setError('');
  };
  useLayoutEffect(() => {
    if (!props.open || !props.criteriaContent) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.querySelector('.confirmation-dialog')) {
        event.preventDefault(); event.stopImmediatePropagation(); navigate('close');
      }
    };
    window.addEventListener('keydown', close, true);
    return () => window.removeEventListener('keydown', close, true);
  }, [props.open, props.hasUnsavedChanges, props.criteriaSaving, saving, testing, !!props.criteriaContent]);
  const perform=async(task:()=>Promise<void>)=>{setError('');setSaving(true);try{await task();}catch(e){setError((e as Error).message);}finally{setSaving(false);}};
  useEffect(() => {
    if (props.open) { setWeights([...props.weights]); setError(''); setConfirmClear(false); setTestResult(null); setTestError(''); }
  }, [props.open, props.model.url, props.model.model, props.model.configured, props.weights.join(',')]);
  useEffect(() => { if (!props.open) setShowKey(false); }, [props.open]);
  useEffect(() => { setTestResult(null); setTestError(''); }, [draft.url, draft.model, draft.key]);
  const total = weights.reduce((sum, value) => sum + value, 0);
  const ring = useMemo(() => weightOption(weights,props.dimensions), [weights,props.dimensions]);
  const modelValues = (): ModelSettings => {
    try {
      const url = new URL(draft.url);
      const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
      if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && local)) || url.search || url.hash || url.username || url.password) throw new Error();
    } catch { throw new Error('请填写有效的 HTTPS API 地址，本机服务可使用 HTTP。'); }
    const key = draft.key.trim() || (draft.provider.startsWith('Ollama') ? 'ollama' : '');
    if ((!key && !keyStored) || !draft.model.trim()) throw new Error('请填写 API 密钥和模型标识。');
    return { ...draft, url: draft.url.trim(), key, model: draft.model.trim(), configured: true };
  };
  const saveModel = (event: React.FormEvent) => {
    event.preventDefault(); setError('');
    try {
      const values = modelValues();
      void perform(()=>props.onModel(values));
    } catch (reason) { setError((reason as Error).message); }
  };
  const testModel = async () => {
    setError(''); setTestResult(null); setTestError(''); setTesting(true);
    try { setTestResult(await props.onTest(modelValues())); }
    catch (reason) { setTestError((reason as Error).message); }
    finally { setTesting(false); }
  };
  return <Dialog.Root open={props.open} onOpenChange={open => { if (open) props.onOpenChange(true); else navigate('close'); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="settings-overlay" />
      <Dialog.Content className="settings-drawer" onCloseAutoFocus={event => { event.preventDefault(); document.querySelector<HTMLButtonElement>('[data-settings-trigger]')?.focus(); }}>
        <div className="drawer-header"><div><Dialog.Title className="font-serif text-[28px]">设置中心</Dialog.Title><Dialog.Description className="sr-only">配置模型、编辑评分标准或管理当前会话数据。</Dialog.Description></div><Dialog.Close asChild><button className="icon-button" aria-label="关闭设置"><Icon name="close" size={21} /></button></Dialog.Close></div>
        <div className="drawer-layout">
          <nav className="settings-menu" aria-label="设置分类">{sections.map(section => <button key={section.key} className={props.section === section.key ? 'is-active' : ''} aria-current={props.section === section.key ? 'page' : undefined}
            onClick={() => { if (section.key !== props.section) navigate(section.key); }}>{section.title}</button>)}</nav>
          <div className="drawer-content">
            {props.section === 'model' && <section className="animate-page-in"><h3 className="font-serif text-section-title">连接模型服务</h3>
              <form onSubmit={saveModel} className="settings-form mt-9"><fieldset disabled={saving || testing} className="criteria-fieldset">
                <label className="field-label" htmlFor="provider">服务商</label>
                <div className="select-wrap"><select id="provider" className="editorial-input appearance-none pr-10" value={draft.provider} onChange={event => { const provider = props.providers.find(item => item.name === event.target.value)!; setShowKey(false); setDraft({ provider: provider.name, url: provider.url, model: '', key: '', configured: false }); }}>
                  {props.providers.map(provider => <option key={provider.name}>{provider.name}</option>)}
                </select><Icon name="chevron" size={16} /></div>
                <label className="field-label" htmlFor="model-url">API 地址</label><input className="editorial-input" id="model-url" type="url" autoComplete="off" value={draft.url} onChange={event => { const url = event.target.value; setShowKey(false); setDraft(value => ({ ...value, url, key: value.url.trim().replace(/\/$/, '') === url.trim().replace(/\/$/, '') ? value.key : '' })); }} placeholder="" required />
                <label className="field-label" htmlFor="model-key">API 密钥</label><div className="relative"><input aria-label="API 密钥" className="editorial-input model-key-input pr-12" id="model-key" type={showKey ? 'text' : 'password'} autoComplete="new-password" data-lpignore="true" data-1p-ignore value={draft.key} onChange={event => setDraft({ ...draft, key: event.target.value })} placeholder="" /><button type="button" className="input-trailing icon-button" aria-label={showKey ? '隐藏密钥' : '显示密钥'} aria-pressed={showKey} disabled={!draft.key} onClick={() => setShowKey(value => !value)}><Icon name={showKey ? 'eyeOff' : 'eye'} size={18}/></button></div>
                <label className="field-label" htmlFor="model-name">模型</label><div className="model-test-row"><input id="model-name" aria-label="模型标识" className="editorial-input" autoComplete="off" value={draft.model} onChange={event => setDraft({ ...draft, model: event.target.value })} placeholder="" required maxLength={200} /><button className="model-test-button" type="button" disabled={saving || testing} onClick={()=>void testModel()}>{testing?'测试中…':'测试'}</button></div>
                {testing && <p className="model-test-feedback" role="status">正在连接模型…</p>}
                {testResult && <p className="model-test-feedback is-success" role="status"><Icon name="check" size={15}/><span>成功 — 模型回复：“{testResult.reply}”</span><small>{(testResult.elapsedMs / 1000).toFixed(2)} s</small></p>}
                {testError && <p className="model-test-feedback is-error" role="alert"><Icon name="close" size={15}/><span>{testError}</span></p>}
                {error && <p role="alert" className="form-error">{error}</p>}
                <div className="drawer-form-footer"><button className="text-action" type="submit" disabled={saving || testing}>{saving?'正在处理…':'保存设置'} <Icon name="arrow" size={18} /></button></div>
              </fieldset>
              </form>
            </section>}
            {props.section === 'criteria' && (props.criteriaContent || <section className="animate-page-in"><h3 className="font-serif text-section-title">维度与权重</h3><p className="section-intro">{props.dimensions.length}个维度，共 100 分。</p>
              <div className="weights-layout"><div className="weight-fields">{props.dimensions.map((name, index) => <label className="weight-row" key={name}><span>{name}</span><span className="inline-flex items-center gap-2"><input aria-label={`${name}权重`} type="number" className="weight-input" min={1} max={100} step={1} value={weights[index]} onChange={event => setWeights(values => values.map((value, i) => i === index ? Math.max(1, Math.min(100, Number(event.target.value))) : value))} /><span className="text-caption text-muted">分</span></span></label>)}</div>
                <div className="weight-figure"><Chart option={ring} label={`七维度权重分布，合计${total}分`} className="h-[190px] w-[190px] max-w-full" /><div className={`weight-total ${Math.abs(total - 100) > .001 ? 'text-accent' : ''}`}><strong className="font-serif">{total}</strong><span>总分 / 100</span></div></div>
              </div>
              <p className="text-caption text-muted mt-5">修改评分条件后，已有评分与复核将清除，需重新评阅。</p>
              {Math.abs(total - 100) > .001 && <p role="alert" className="form-error">当前合计 {total} 分，请调整至 100 分后保存。</p>}
              {error&&<p role="alert" className="form-error">{error}</p>}<div className="drawer-form-footer"><button className="text-action" disabled={saving||Math.abs(total - 100) > .001} onClick={() => void perform(()=>props.onWeights(weights))}>保存评分标准 <Icon name="arrow" size={18} /></button></div>
            </section>)}
            {props.section === 'data' && <section className="animate-page-in"><h3 className="font-serif text-section-title">会话数据</h3><p className="section-intro">刷新保留当前会话；重启后端或会话过期后清除论文。</p>
              <dl className="session-data"><div><dt>当前论文</dt><dd className="font-serif">{props.paperCount}<small>篇</small></dd></div><div><dt>会话数据估算</dt><dd className="font-serif">{formatBytes(props.bytes)}</dd></div></dl>
              <p className="text-caption text-muted mt-6">当前上传PDF的内存大小，不含解析与模型运行开销。</p>
              <div className="data-clear">
                {error&&<p role="alert" className="form-error">{error}</p>}{!confirmClear ? <button className="text-action text-accent" onClick={() => setConfirmClear(true)}>清空当前会话 <Icon name="trash" size={17} /></button> : <div><p className="mb-4">将清除当前入口的论文与复核记录，保留本机模型配置。</p><div className="flex gap-6"><button className="text-action text-accent" disabled={saving} onClick={()=>void perform(props.onClear)}>确认清空</button><button className="quiet-link" onClick={() => setConfirmClear(false)}>取消</button></div></div>}
              </div>
            </section>}
          </div>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
    <ConfirmDialog open={pendingNavigation !== null} title="放弃未保存的修改？" description="存在未保存的修改，是否确认放弃？" confirmText="确认放弃"
      onCancel={() => setPendingNavigation(null)} onConfirm={() => {
        props.onDiscardChanges?.();
        if (pendingNavigation === 'close') props.onOpenChange(false); else if (pendingNavigation) props.onSection(pendingNavigation);
        setPendingNavigation(null); setError('');
      }} />
  </Dialog.Root>;
}
