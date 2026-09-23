/* Presentation only. All access, validation and writes are server-side. */
(() => {
  const form = document.querySelector('form[data-unsaved]');
  let dirty = false;
  form?.addEventListener('input', () => { dirty = true; });
  form?.addEventListener('change', () => { dirty = true; });
  form?.addEventListener('submit', () => { dirty = false; });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  document.querySelector('#add-option')?.addEventListener('click', () => {
    const total = document.querySelector('#id_options-TOTAL_FORMS');
    const index = Number(total.value);
    const template = document.querySelector('#option-template');
    // Only the static, server-rendered template is inserted; no user HTML.
    document.querySelector('#option-list').insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', index));
    const positions = [...document.querySelectorAll('#option-list input[name$="-position"]')];
    positions.at(-1).value = Math.max(0, ...positions.slice(0, -1).map(el => Number(el.value) || 0)) + 1;
    total.value = index + 1;
    dirty = true;
    document.querySelector(`#id_options-${index}-text`).focus();
  });
})();
