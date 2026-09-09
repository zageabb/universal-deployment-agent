const grid = document.getElementById('app-grid');
const message = document.getElementById('registry-message');
const empty = document.getElementById('empty-message');
let lastSnapshot;
async function refresh() {
  try {
    const response = await fetch('/api/applications', {cache: 'no-store'});
    if (!response.ok) throw new Error('Directory unavailable');
    const {applications} = await response.json();
    const snapshot = JSON.stringify(applications);
    if (snapshot !== lastSnapshot) {
      const nodes = applications.map(app => {
        const link = document.createElement('a');
        link.className = 'app-card';
        link.href = app.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.setAttribute('aria-label', `${app.title} (opens in a new tab)`);
        const top = document.createElement('div'); top.className = 'card-top';
        const icon = document.createElement('span'); icon.className = 'app-icon'; icon.textContent = app.initials; icon.setAttribute('aria-hidden', 'true');
        const arrow = document.createElement('span'); arrow.className = 'open-icon'; arrow.textContent = '↗'; arrow.setAttribute('aria-hidden', 'true');
        top.append(icon, arrow);
        const title = document.createElement('h2'); title.textContent = app.title;
        const address = document.createElement('span'); address.className = 'address'; address.textContent = app.address;
        link.append(top, title, address);
        return link;
      });
      const focusedUrl = grid.contains(document.activeElement) ? document.activeElement.href : null;
      grid.replaceChildren(...nodes);
      if (focusedUrl) nodes.find(node => node.href === focusedUrl)?.focus();
      document.getElementById('app-count').textContent = `${applications.length} applications`;
      empty.hidden = applications.length > 0;
      lastSnapshot = snapshot;
    }
    message.hidden = true;
  } catch {
    message.hidden = false;
  }
}
setInterval(refresh, 60000);
