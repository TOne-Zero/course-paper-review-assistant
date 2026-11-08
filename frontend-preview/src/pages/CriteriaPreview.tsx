import { useState } from 'react';
import course from '../../../rubrics/00_course_demo.json';
import general from '../../../rubrics/01_general.json';
import research from '../../../rubrics/02_research.json';
import { CriteriaEditor, type CriteriaStandard, type Dimension } from '../components/CriteriaEditor';
import { SettingsDrawer } from '../components/SettingsDrawer';
import { Icon } from '../components/Icon';
import { EMPTY_MODEL, type SettingsSection } from '../model';

const standards: CriteriaStandard[] = [course, general, research].map(standard => ({
  id: standard.id, name: standard.name.replace(/（.*?）/g, ''),
  dimensions: standard.dimensions.map(dimension => ({
    id: dimension.id, name: dimension.name, weight: dimension.max_score,
    detailText: 'checklist' in dimension ? (dimension.checklist as string[]).join('；') : dimension.description,
  })),
}));

export default function CriteriaPreview() {
  const [open, setOpen] = useState(true), [section, setSection] = useState<SettingsSection>('criteria');
  const [dirty, setDirty] = useState(false), [revision, setRevision] = useState(0);
  const [activeId, setActiveId] = useState('course_demo');
  const [savedValues, setSavedValues] = useState<Record<string, Dimension[]>>({});
  const [notice, setNotice] = useState('');
  const discard = () => { setDirty(false); setRevision(value => value + 1); };
  return <div className="criteria-preview-page">
    <header className="site-masthead"><a className="brand font-serif" href="/?view=workspace">结课论文评价助手</a><span className="preview-label">评分标准 · 前端预览</span></header>
    <main className="editorial-page criteria-preview-landing"><h1 className="font-serif text-headline">把评阅要求，写得更清楚。</h1>
      <p>三套标准，同一种编辑方式。</p><button data-settings-trigger className="text-action" onClick={() => { setSection('criteria'); setOpen(true); }}>查看评分标准<Icon name="arrow" size={18} /></button>
      <a className="quiet-link" href="/?view=workspace">返回正式工作台</a>
    </main>
    <SettingsDrawer open={open} onOpenChange={setOpen} section={section} onSection={setSection} model={EMPTY_MODEL}
      weights={standards[0].dimensions.map(d => d.weight)} dimensions={standards[0].dimensions.map(d => d.name)}
      providers={[{ name: '自定义', url: '' }]} bytes={0} paperCount={0}
      onModel={async () => { setNotice('当前为评分标准预览，请在正式工作台配置模型。'); }}
      onWeights={async () => {}} onClear={async () => { setNotice('当前为前端预览，没有正式会话数据。'); }} onTest={async () => {throw new Error('请在正式工作台测试模型。');}}
      hasUnsavedChanges={dirty} onDiscardChanges={discard}
      criteriaContent={<CriteriaEditor key={revision} standards={standards} initialId={activeId} savedValues={savedValues} onDirtyChange={setDirty} onStandardChange={setActiveId}
        onSave={async (id, dimensions) => { setSavedValues(values => ({ ...values, [id]: dimensions })); }} />}
    />
    {notice && <div className="toast is-visible" role="status" onClick={() => setNotice('')}>{notice}</div>}
  </div>;
}
