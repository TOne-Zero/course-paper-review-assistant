import * as Dialog from '@radix-ui/react-dialog';
import { useLayoutEffect } from 'react';

export function ConfirmDialog({ open, title, description, confirmText, cancelText = '继续编辑', onCancel, onConfirm }: {
  open: boolean; title: string; description: string; confirmText: string;
  cancelText?: string;
  onCancel: () => void; onConfirm: () => void;
}) {
  useLayoutEffect(() => {
    if (!open) return;
    // Handle the nested dialog before the drawer's document-level Escape listener.
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); onCancel(); }
    };
    window.addEventListener('keydown', cancel, true);
    return () => window.removeEventListener('keydown', cancel, true);
  }, [open, onCancel]);
  return <Dialog.Root open={open} onOpenChange={value => { if (!value) onCancel(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="confirmation-overlay" />
      <Dialog.Content role="alertdialog" className="confirmation-dialog" onOpenAutoFocus={event => {
        event.preventDefault(); document.querySelector<HTMLButtonElement>('[data-confirm-cancel]')?.focus();
      }} onEscapeKeyDown={event => { event.preventDefault(); event.stopPropagation(); onCancel(); }}
        onPointerDownOutside={event => { event.preventDefault(); onCancel(); }}>
        <Dialog.Title className="font-serif text-section-title">{title}</Dialog.Title>
        <Dialog.Description className="confirmation-description">{description}</Dialog.Description>
        <div className="confirmation-actions">
          <button data-confirm-cancel className="quiet-link" onClick={onCancel}>{cancelText}</button>
          <button className="text-action text-accent" onClick={onConfirm}>{confirmText}</button>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
