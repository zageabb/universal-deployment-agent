(() => {
  function setup(root) {
    const nav = root.querySelector('[data-group-nav]');
    const count = root.querySelector('[data-visible-count]');
    if (!nav) return;

    const storageKey = root.dataset.groupStorageKey || 'uda-application-group';
    let activeGroup = 'all';
    try {
      activeGroup = sessionStorage.getItem(storageKey) || 'all';
    } catch {
      activeGroup = 'all';
    }

    const cards = () => Array.from(root.querySelectorAll('[data-app-group]'));
    const buttons = () => Array.from(nav.querySelectorAll('[data-group-button]'));

    function persist(group) {
      try { sessionStorage.setItem(storageKey, group); } catch { /* storage may be unavailable */ }
    }

    function apply(group = activeGroup) {
      const allCards = cards();
      const available = new Set(allCards.map(card => card.dataset.appGroup));
      if (group !== 'all' && !available.has(group)) group = 'all';
      activeGroup = group;

      let visible = 0;
      allCards.forEach(card => {
        const show = group === 'all' || card.dataset.appGroup === group;
        card.hidden = !show;
        if (show) visible += 1;
      });
      buttons().forEach(button => {
        const selected = button.dataset.group === group;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-pressed', selected ? 'true' : 'false');
      });
      if (count) {
        const total = allCards.length;
        const noun = total === 1 ? 'application' : 'applications';
        count.textContent = group === 'all' ? total + ' ' + noun : visible + ' of ' + total + ' ' + noun;
      }
      persist(group);
    }

    nav.addEventListener('click', event => {
      const button = event.target.closest('[data-group-button]');
      if (!button || !nav.contains(button)) return;
      apply(button.dataset.group || 'all');
    });
    root.addEventListener('uda:applications-updated', () => apply(activeGroup));
    apply(activeGroup);
  }

  function init() {
    document.querySelectorAll('[data-group-root]').forEach(setup);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
