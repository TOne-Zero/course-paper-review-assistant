import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useLayoutEffect, useState } from 'react';

export interface ArchiveValues { className: string; course: string }

export function ArchiveDialog({ open, busy, defaultClassName = '', onCancel, onConfirm }: {
  open: boolean; busy: boolean; defaultClassName?: string;
  onCancel: () => void; onConfirm: (values: ArchiveValues) => void;
}) {
  const [className, setClassName] = useState(defaultClassName);
  const [course, setCourse] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setClassName(defaultClassName); setCourse(''); setError(''); } }, [open, defaultClassName]);
  useLayoutEffect(() => {
    if (!open) return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); if (!busy) onCancel(); }
    };
    window.addEventListener('keydown', cancel, true);
    return () => window.removeEventListener('keydown', cancel, true);
  }, [open, busy, onCancel]);
  const submit = () => {
    const name = className.trim();
    if (!name) { setError('请填写班级名称，用于在历史存档中归类。'); return; }
    if (name.length > 40) { setError('班级名称最多40个字符。'); return; }
    if (course.trim().length > 60) { setError('课程名称最多60个字符。'); return; }
    setError(''); onConfirm({ className: name, course: course.trim() });
  };
  return <Dialog.Root open={open} onOpenChange={value => { if (!value && !busy) onCancel(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="confirmation-overlay" />
      <Dialog.Content role="dialog" className="confirmation-dialog archive-dialog" onOpenAutoFocus={event => event.preventDefault()}
        onEscapeKeyDown={event => { event.preventDefault(); event.stopPropagation(); if (!busy) onCancel(); }}
        onPointerDownOutside={event => { event.preventDefault(); if (!busy) onCancel(); }}>
        <Dialog.Title className="font-serif text-section-title">归档到班级</Dialog.Title>
        <Dialog.Description className="confirmation-description">
          把本批已完整评分的论文保存到班级成绩存档；同一班级可多次归档。缺分论文不会写入存档。
        </Dialog.Description>
        <div className="archive-form">
          <label className="field-label" htmlFor="archive-class">班级名称</label>
          <input id="archive-class" className="editorial-input" maxLength={40} value={className} disabled={busy}
            placeholder="如 2024级数字媒体技术1班" onChange={event => setClassName(event.target.value)} />
          <label className="field-label" htmlFor="archive-course">课程名称（选填）</label>
          <input id="archive-course" className="editorial-input" maxLength={60} value={course} disabled={busy}
            placeholder="如 新媒体研究方法" onChange={event => setCourse(event.target.value)} />
          {error && <p className="form-error" role="alert">{error}</p>}
        </div>
        <div className="confirmation-actions">
          <button className="quiet-link" disabled={busy} onClick={onCancel}>取消</button>
          <button className="text-action text-accent" disabled={busy} onClick={submit}>{busy ? '正在归档…' : '确认归档'}</button>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
