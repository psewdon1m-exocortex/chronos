// Shared interaction rules; vendored with the Settings components.
export function bindDialogInteraction(dialog) {
  const header = dialog.querySelector('header');
  const controller = new AbortController(), { signal } = controller;
  let x = 0, y = 0, drag;
  const paint = () => { dialog.style.transform = `translate(${x}px, ${y}px)`; };
  function clamp() {
    const box = dialog.getBoundingClientRect();
    x += Math.min(0, innerWidth - 8 - box.right) + Math.max(0, 8 - box.left);
    y += Math.min(0, innerHeight - 8 - box.bottom) + Math.max(0, 8 - box.top);
    paint();
  }
  header?.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button,input,a,select')) return;
    drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY };
    header.setPointerCapture(event.pointerId); event.preventDefault();
  }, { signal });
  header?.addEventListener('pointermove', event => {
    if (!drag || drag.pointer !== event.pointerId) return;
    x += event.clientX - drag.x; y += event.clientY - drag.y;
    drag.x = event.clientX; drag.y = event.clientY; paint(); clamp();
  }, { signal });
  const stop = () => { drag = undefined; };
  header?.addEventListener('pointerup', stop, { signal });
  header?.addEventListener('lostpointercapture', stop, { signal });
  window.addEventListener('resize', clamp, { signal });
  dialog.addEventListener('close', () => controller.abort(), { once: true });
}

// Read untransformed layout dimensions so hover never compounds its own scale.
export function bindActionGeometry(root) {
  root = root.closest('.settings-stack,.settings-list,.settings,.grid') || root;
  const selector = 'button:not(.close,.drag,.drag-handle,.drag-mark,.drag-dots,.card-handle),a[download]';
  const measure = entries => {
    for (const { target } of entries) {
      const w = target.offsetWidth, h = target.offsetHeight, growth = Math.min(w, h) * .05;
      if (w && h) {
        target.style.setProperty('--exo-scale-x', String((w + growth) / w));
        target.style.setProperty('--exo-scale-y', String((h + growth) / h));
      }
    }
  };
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : { observe: target => measure([{target}]), unobserve() {}, disconnect() {} };
  const seen = new Set();
  const scan = () => {
    for (const target of seen) if (!root.contains(target)) { observer.unobserve(target); seen.delete(target); }
    for (const target of root.querySelectorAll(selector)) if (!seen.has(target)) { seen.add(target); observer.observe(target); }
  };
  const resize = () => measure([...seen].map(target => ({target})));
  window.addEventListener("resize", resize);
  const mutations = new MutationObserver(scan); mutations.observe(root, { childList: true, subtree: true }); scan();
  return () => { window.removeEventListener("resize", resize); mutations.disconnect(); observer.disconnect(); seen.clear(); };
}
