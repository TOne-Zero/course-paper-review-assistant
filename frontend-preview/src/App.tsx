import {useEffect,useMemo,useState} from 'react';
import {Cover} from './pages/Cover';
import {Workspace} from './pages/Workspace';
import {Review} from './pages/Review';
import {SettingsDrawer} from './components/SettingsDrawer';
import {Icon} from './components/Icon';
import {CriteriaEditor} from './components/CriteriaEditor';
import {ConfirmDialog} from './components/ConfirmDialog';
import {criteriaStandards,rubricDimensions} from './criteria';
import {DEFAULT_WEIGHTS,DIMENSIONS,EMPTY_MODEL,readPage,type AppState,type Page,type SettingsSection,type Paper,type ModelTestResult} from './model';
import {request,downloadReports,simulation} from './api';

export default function App(){
  const [page,setPage]=useState<Page>(readPage),[state,setState]=useState<AppState|null>(null),[selected,setSelected]=useState('');
  const [settingsOpen,setSettingsOpen]=useState(()=>new URLSearchParams(location.search).get('settings')==='criteria'),[section,setSection]=useState<SettingsSection>(()=>new URLSearchParams(location.search).get('settings')==='criteria'?'criteria':'model'),[toast,setToast]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[consent,setConsent]=useState(false);
  const [criteriaDirty,setCriteriaDirty]=useState(false),[criteriaSaving,setCriteriaSaving]=useState(false),[criteriaRevision,setCriteriaRevision]=useState(0),[editingCriteriaId,setEditingCriteriaId]=useState(''),[pendingCriteria,setPendingCriteria]=useState<string|null>(null);
  const [confirmSending,setConfirmSending]=useState(false);
  const standards=useMemo(()=>criteriaStandards(state?.rubricPresets||state?.rubrics||[]),[state?.rubricPresets,state?.rubrics]);
  const criteriaValues=useMemo(()=>Object.fromEntries((state?.rubrics||[]).map(r=>[r.id,rubricDimensions(r)])),[state?.rubrics]);
  const criteriaVersions=useMemo(()=>Object.fromEntries((state?.rubrics||[]).map(r=>[r.id,r.version])),[state?.rubrics]);
  const papers=state?.papers||[],weights=state?.rubric.dimensions.map(d=>d.max_score)||DEFAULT_WEIGHTS,dimensions=state?.rubric.dimensions.map(d=>d.name)||DIMENSIONS;
  const refresh=async()=>{try{setState(await request('/state'));setError('');}catch(e){setError((e as Error).message);}};
  useEffect(()=>{void refresh();},[]);
  useEffect(()=>{if(settingsOpen)void refresh();},[settingsOpen]);
  useEffect(()=>{if(!state?.running)return;const timer=setInterval(()=>void refresh(),800);return()=>clearInterval(timer);},[state?.running]);
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(''),6500);return()=>clearTimeout(t);},[toast]);
  const navigate=(next:Page)=>{const url=new URL(location.href);if(next==='cover')url.searchParams.delete('view');else url.searchParams.set('view',next);history.pushState(null,'',url);setPage(next);scrollTo(0,0);};
  useEffect(()=>{const change=()=>{setPage(readPage());scrollTo(0,0);};addEventListener('popstate',change);return()=>removeEventListener('popstate',change);},[]);
  const action=async(path:string,body?:unknown,method?:string)=>{setBusy(true);setToast('');try{const value=await request(path,body,method);setState(value);setError('');return value;}catch(e){setToast((e as Error).message);throw e;}finally{setBusy(false);}};
  const safe=(promise:Promise<unknown>)=>{void promise.catch(()=>{});};
  const selectCriteria=async(id:string)=>{await action('/rubric',{id,select:true});setConsent(false);setEditingCriteriaId(id);};
  const openModel=()=>{setSection('model');setSettingsOpen(true);};
  const addFiles=async(files:File[])=>{if(!files.length)return;if(files.length+papers.length>10){setToast('每批最多10篇，请减少文件。');return;}if(files.some(f=>!(/\.(pdf|docx?)$/i).test(f.name)||f.size>20*1024*1024)){setToast('请选择单篇不超过20 MB的Word或PDF文件（.doc、.docx、.pdf）。');return;}if(files.reduce((n,f)=>n+f.size,0)+(state?.bytes||0)>50*1024*1024){setToast('本批次不能超过50 MB。');return;}const form=new FormData();files.forEach(f=>form.append('files',f));setConsent(false);await action('/upload',form);setToast('上传完成，已解析论文文字。');};
  const start=async()=>{if(!simulation&&!state?.model.configured){openModel();return;}if(state?.running){await action('/pause',{});setToast('将在当前篇完成后暂停后续任务。');return;}if(!simulation&&!consent){setConfirmSending(true);return;}await action('/start',{consent});};
  const exportPapers=async(values?:Paper[])=>{try{await downloadReports(values?.map(p=>p.id));setToast('报告已导出。');}catch(e){setToast((e as Error).message);}};
  return <>
    <a className="skip-link" href="#main-content">跳至主要内容</a>
    {page==='cover'?<Cover enter={()=>navigate('workspace')}/>:<>
      <header className="site-masthead"><button className="brand font-serif" onClick={()=>navigate('cover')}>结课论文评价助手</button><nav className="primary-nav" aria-label="主导航"><button aria-current={page==='workspace'?'page':undefined} className={page==='workspace'?'is-active':''} onClick={()=>navigate('workspace')}>批量评阅</button><button aria-current={page==='review'?'page':undefined} className={page==='review'?'is-active':''} onClick={()=>navigate('review')}>结果复核</button><span className="mobile-preview">{simulation?'模拟运行':'正式评阅'}</span></nav><div className="masthead-tools"><span className="preview-label">{simulation?'模拟运行 · 固定比例演示':'正式评阅'}</span><button data-settings-trigger className="icon-button settings-trigger" onClick={()=>setSettingsOpen(true)} aria-label="打开设置中心"><Icon name="settings" size={23}/></button></div></header>
      <div id="main-content" tabIndex={-1}>
        {error&&<div className="editorial-page configuration-note" role="alert"><span>{error}</span><button className="quiet-link" onClick={()=>void refresh()}>重新连接</button></div>}{!state&&!error&&<p className="editorial-page py-8" role="status">正在连接本机服务…</p>}
        {page==='workspace'?<Workspace papers={papers} weights={weights} dimensions={dimensions} criteria={state?.rubric.id||''} rubrics={state?.rubrics||[]} running={!!state?.running} busy={busy||!state} simulation={simulation} progress={state?.progress||''} consent={consent} onConsent={setConsent} configured={!!state?.model.configured} onSettings={openModel}
          onCriteria={id=>{if(papers.some(p=>p.report))setPendingCriteria(id);else safe(selectCriteria(id));}}
          onFiles={files=>safe(addFiles(files))} onRemove={id=>safe(action('/papers/'+id,undefined,'DELETE'))} onSelect={id=>{setSelected(id);navigate('review');}} onStart={()=>safe(start())} onDemo={()=>safe(action('/demo',{}))} onExport={()=>void exportPapers()}/>
          :<Review papers={papers} weights={weights} dimensions={dimensions} selected={selected} onSelect={setSelected} onBack={()=>navigate('workspace')} onSave={async(id,scores,note)=>{const paper=papers.find(p=>p.id===id);await action('/reviews/'+id,{scores,note,evaluationId:paper?.report?.evaluation_id});setToast('教师复核已记录。');}} onExport={values=>void exportPapers(values)}/>}
      </div>
    </>}
    <SettingsDrawer open={settingsOpen} onOpenChange={setSettingsOpen} section={section} onSection={setSection} model={state?.model||EMPTY_MODEL} weights={weights} dimensions={dimensions} providers={state?.providers||[]} bytes={state?.bytes||0} paperCount={papers.length}
      hasUnsavedChanges={criteriaDirty} criteriaSaving={criteriaSaving} onDiscardChanges={()=>{setCriteriaDirty(false);setCriteriaRevision(v=>v+1);}}
      criteriaContent={state&&standards.length?<CriteriaEditor key={criteriaRevision} standards={standards} initialId={editingCriteriaId||state.rubric.id} savedValues={criteriaValues} versions={criteriaVersions}
        preview={false} appliedId={state.rubric.id} disabled={state.running} onDirtyChange={setCriteriaDirty} onSavingChange={setCriteriaSaving} onStandardChange={setEditingCriteriaId}
        onSave={async(id,dimensions,version)=>{const next=await action('/rubric',{id,dimensions,expectedVersion:version,confirm:true});setConsent(false);setToast('评分标准已保存，将用于后续评阅。');return next.rubric.version;}}/>:<p role="status">正在读取评分标准…</p>}
      onModel={async values=>{await action('/model',values);setConsent(false);}} onTest={values=>request<ModelTestResult>('/model/test',values)}
      onWeights={async values=>{await action('/rubric',{id:state?.rubric.id,weights:values});setConsent(false);setSettingsOpen(false);setToast('评分标准已更新，已有评分需重新评阅。');}} onClear={async()=>{await action('/clear',{});setConsent(false);setSettingsOpen(false);setToast('当前入口的论文与复核记录已清空。');}}/>
    <div className={`toast ${toast?'is-visible':''}`} role="status" aria-live="polite">{toast}</div>
    <ConfirmDialog open={pendingCriteria!==null} title="确认切换评分标准" description="警告：修改评分条件后，已有评分与复核将被清除，需重新评阅。是否确认修改？" confirmText="确认修改"
      onCancel={()=>setPendingCriteria(null)} onConfirm={()=>{if(pendingCriteria)safe(selectCriteria(pendingCriteria));setPendingCriteria(null);}}/>
    <ConfirmDialog open={confirmSending} title="确认发送论文" description={`请确认将本批论文文本发送至已配置的模型服务。本批共 ${papers.length} 篇。`} confirmText="同意并开始" cancelText="取消"
      onCancel={()=>setConfirmSending(false)} onConfirm={()=>{setConfirmSending(false);setConsent(true);safe(action('/start',{consent:true}));}}/>
  </>;
}
