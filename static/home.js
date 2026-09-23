const root = document.querySelector('[data-group-root]');
const grid = document.getElementById('app-grid');
const groupNav = document.querySelector('[data-group-nav]');
const message = document.getElementById('registry-message');
const empty = document.getElementById('empty-message');
let lastSnapshot;

function groupButton(name, count, all = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'group-button';
  button.dataset.groupButton = '';
  button.dataset.group = all ? 'all' : name;
  button.setAttribute('aria-pressed', 'false');
  const label = document.createElement('span');
  label.textContent = all ? 'All applications' : name;
  const badge = document.createElement('span');
  badge.className = 'group-count';
  badge.textContent = count;
  button.append(label, badge);
  return button;
}

function appCard(app) {
  const link = document.createElement('a');
  link.className = 'app-card';
  link.href = app.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.dataset.appGroup = app.group || 'Other';
  link.setAttribute('aria-label', app.title + ' (opens in a new tab)');
  const top = document.createElement('div'); top.className = 'card-top';
  const icon = document.createElement('span'); icon.className = 'app-icon'; icon.textContent = app.initials; icon.setAttribute('aria-hidden', 'true');
  const arrow = document.createElement('span'); arrow.className = 'open-icon'; arrow.textContent = '↗'; arrow.setAttribute('aria-hidden', 'true');
  top.append(icon, arrow);
  const title = document.createElement('h2'); title.textContent = app.title;
  const group = document.createElement('span'); group.className = 'app-group'; group.textContent = app.group || 'Other';
  const address = document.createElement('span'); address.className = 'address'; address.textContent = app.address;
  link.append(top, title, group, address);
  return link;
}

async function refresh() {
  try {
    const response = await fetch('/api/applications', {cache: 'no-store'});
    if (!response.ok) throw new Error('Directory unavailable');
    const {applications, groups = []} = await response.json();
    const snapshot = JSON.stringify({applications, groups});
    if (snapshot !== lastSnapshot) {
      const nodes = applications.map(appCard);
      const focusedUrl = grid.contains(document.activeElement) ? document.activeElement.href : null;
      grid.replaceChildren(...nodes);
      groupNav.replaceChildren(
        groupButton('all', applications.length, true),
        ...groups.map(group => groupButton(group.name, group.count))
      );
      if (focusedUrl) nodes.find(node => node.href === focusedUrl)?.focus();
      empty.hidden = applications.length > 0;
      lastSnapshot = snapshot;
      root?.dispatchEvent(new Event('uda:applications-updated'));
    }
    message.hidden = true;
  } catch {
    message.hidden = false;
  }
}
setInterval(refresh, 60000);
