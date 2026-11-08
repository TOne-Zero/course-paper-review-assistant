/* 只增强本项目摄影入口；按钮和静态阅读在脚本禁用时仍可用。 */
(() => {
  window.__paperEntranceCleanup?.();
  let retry = 0;
  const mount = () => {
    const root = document.querySelector('.entrance');
    if (!root) {
      if (retry++ < 90) requestAnimationFrame(mount);
      return;
    }
    const controller = new AbortController();
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let x = 0, y = 0, targetX = 0, targetY = 0;
    const enabled = () => !media.matches && !document.hidden && !root.classList.contains('entrance-paused');
    const paint = () => {
      frame = 0;
      if (!enabled()) return;
      x += (targetX - x) * .12;
      y += (targetY - y) * .12;
      root.style.setProperty('--pointer-x', `${(x * 24).toFixed(2)}px`);
      root.style.setProperty('--pointer-y', `${(y * 16).toFixed(2)}px`);
      root.style.setProperty('--pointer-tilt', `${(x * 3).toFixed(2)}deg`);
      if (Math.abs(targetX-x) + Math.abs(targetY-y) > .002) frame = requestAnimationFrame(paint);
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      root.classList.toggle('entrance-hidden', document.hidden);
      if (media.matches) {
        root.style.setProperty('--pointer-x','0px');
        root.style.setProperty('--pointer-y','0px');
        root.style.setProperty('--pointer-tilt','0deg');
      }
    };
    document.addEventListener('pointermove', (event) => {
      if (!enabled() || event.pointerType === 'touch') return;
      targetX = event.clientX / innerWidth * 2 - 1;
      targetY = event.clientY / innerHeight * 2 - 1;
      if (!frame) frame = requestAnimationFrame(paint);
    }, {signal:controller.signal,passive:true});
    document.addEventListener('pointerleave', () => {
      targetX = targetY = 0;
      if (enabled() && !frame) frame = requestAnimationFrame(paint);
    }, {signal:controller.signal});
    document.addEventListener('visibilitychange',stop,{signal:controller.signal});
    media.addEventListener('change',stop,{signal:controller.signal});
    const observer = new MutationObserver(() => { if (!root.isConnected) cleanup(); });
    const cleanup = () => { controller.abort(); cancelAnimationFrame(frame); observer.disconnect(); };
    observer.observe(document.body,{childList:true,subtree:true});
    root.dataset.enhanced = 'true';
    stop();
    window.__paperEntranceCleanup = cleanup;
  };
  mount();
})();
