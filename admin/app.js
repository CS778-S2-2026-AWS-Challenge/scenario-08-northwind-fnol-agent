const ADMIN_API_BASE = globalThis.NORTHWIND_ADMIN_API_BASE || 'http://127.0.0.1:8000/internal/v1/admin';
const TOKEN_KEY = 'northwind.adminToken';

const modules = [
  { id: 'system', label: 'System', description: 'Configuration status across the Control Plane.' },
  { id: 'models', label: 'Models', domain: 'model', description: 'Provider-neutral model configuration and publication state.' },
  { id: 'data', label: 'Data', domain: 'data_profile', description: 'Runtime data profile configuration and capability state.' },
  { id: 'knowledge', label: 'Knowledge', domain: 'knowledge', description: 'Governed knowledge configuration and version state.' },
  { id: 'agent-rules', label: 'Agent Rules', domain: 'agent_rule', description: 'Versioned Agent rules and their validation state.' },
  { id: 'integrations', label: 'Integrations', domain: 'integration', description: 'Safe integration configuration metadata.' },
  { id: 'evaluation', label: 'Evaluation', domain: 'evaluation', description: 'Evaluation configuration and release evidence.' },
  { id: 'operations', label: 'Operations', domain: 'operational_configuration', description: 'Operational limits and runtime configuration.' },
  { id: 'access', label: 'Access', domain: 'access', description: 'Administration access configuration.' },
  { id: 'audit', label: 'Audit', unavailable: true, description: 'Restricted configuration audit history.' },
];

const byId = id => document.getElementById(id);
let records = [];
let activeModule = moduleFromLocation();
let authorised = false;

function token() {
  try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}

function moduleFromLocation() {
  const id = location.hash.replace(/^#\/?/, '') || 'system';
  return modules.some(item => item.id === id) ? id : 'system';
}

function setView(view) {
  ['loadingState', 'unauthorisedState', 'errorState', 'consoleView'].forEach(id => { byId(id).hidden = id !== view; });
}

function announce(message) { byId('liveRegion').textContent = message; }

async function adminRequest(path = '/configurations') {
  let response;
  try {
    response = await fetch(`${ADMIN_API_BASE}${path}`, { headers: { Authorization: `Bearer ${token()}` } });
  } catch {
    throw Object.assign(new Error('The Admin API could not be reached. Start the API or check its configured address, then retry.'), { code: 'NETWORK_ERROR' });
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(payload?.error?.message || 'The Admin API did not return configuration status. Check the service and retry.');
    error.status = response.status; error.code = payload?.error?.code; error.requestId = payload?.error?.request_id;
    throw error;
  }
  return payload;
}

function renderNavigation() {
  byId('moduleNavigation').innerHTML = modules.map(item => `
    <a class="nav-link" href="#/${item.id}" ${item.id === activeModule ? 'aria-current="page"' : ''}>
      <span>${item.label}</span>${item.unavailable ? '<span class="nav-status">Planned</span>' : ''}
    </a>`).join('');
}

function statusBadge(state) {
  const label = String(state || 'unavailable').replaceAll('_', ' ');
  const tone = state === 'published' ? 'success' : state === 'awaiting_approval' || state === 'draft' ? 'warning' : state === 'withdrawn' ? 'danger' : '';
  return `<span class="badge${tone ? ` badge--${tone}` : ''}">${escapeHtml(label)}</span>`;
}

function escapeHtml(value) {
  const node = document.createElement('span'); node.textContent = value == null ? '–' : String(value); return node.innerHTML;
}

function recordName(record) {
  return record.values?.name || record.values?.label || record.configuration_id;
}

function renderRecords(items) {
  if (!items.length) return `<div class="notice"><div><h2>No configuration records</h2><p>No records exist for this module. Configuration creation is not available in this console release.</p></div></div>`;
  return `<div class="table-wrap"><table><thead><tr><th scope="col">Configuration</th><th scope="col">Status</th><th scope="col">Revision</th><th scope="col">Validation</th><th scope="col">Publication / rollback</th></tr></thead><tbody>${items.map(record => {
    const validation = record.validation_evidence?.length ? `${record.validation_evidence.length} result${record.validation_evidence.length === 1 ? '' : 's'} recorded` : 'Not validated';
    const publication = record.state === 'published' ? `Active${record.effective_time ? ` since ${new Date(record.effective_time).toLocaleString()}` : ''}` : record.rollback_target ? `Rollback target: ${record.rollback_target}` : record.previous_version ? `Previous version: ${record.previous_version}` : 'Not published';
    return `<tr><td><span class="item-name">${escapeHtml(recordName(record))}</span><span class="item-id">${escapeHtml(record.configuration_id)}</span></td><td>${statusBadge(record.state)}</td><td>${escapeHtml(record.revision)}</td><td>${escapeHtml(validation)}</td><td>${escapeHtml(publication)}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function renderSystem() {
  const published = records.filter(item => item.state === 'published').length;
  const needsAttention = records.filter(item => ['draft', 'awaiting_approval'].includes(item.state)).length;
  return `<dl class="summary-list"><div><dt>Configuration records</dt><dd>${records.length}</dd></div><div><dt>Published</dt><dd>${published}</dd></div><div><dt>Needs review</dt><dd>${needsAttention}</dd></div></dl>
    <div class="system-grid">
      <section class="records-panel" aria-labelledby="recordsHeading">
        <header class="panel-heading"><div><p class="section-label">Control Plane</p><h2 id="recordsHeading">Configuration records</h2></div><span class="record-count">${records.length}</span></header>
        <div class="records-content">${renderRecords(records)}</div>
      </section>
      <section class="state-guide" aria-labelledby="lifecycleHeading">
        <header class="panel-heading"><div><p class="section-label">Governance</p><h2 id="lifecycleHeading">Lifecycle status</h2></div></header>
        <dl class="lifecycle-list">
          <div class="lifecycle-row lifecycle-row--validation"><dt><span class="lifecycle-icon" aria-hidden="true">✓</span>Validation</dt><dd>Failed checks remain unpublished and return field or scenario evidence from the Admin API.</dd></div>
          <div class="lifecycle-row lifecycle-row--publish"><dt><span class="lifecycle-icon" aria-hidden="true">↑</span>Publish</dt><dd>Only validated, authorised revisions can become immutable active configuration.</dd></div>
          <div class="lifecycle-row lifecycle-row--rollback"><dt><span class="lifecycle-icon" aria-hidden="true">↶</span>Rollback</dt><dd>An authorised rollback publishes a prior approved version as a new record and preserves history.</dd></div>
        </dl>
      </section>
    </div>`;
}

function renderModule() {
  if (!authorised) return;
  const module = modules.find(item => item.id === activeModule) || modules[0];
  byId('pageTitle').textContent = module.label; byId('pageDescription').textContent = module.description;
  if (module.unavailable) {
    byId('moduleContent').innerHTML = '<div class="notice notice--warning"><div><h2>Not implemented in this release</h2><p>No global audit search or audit controls are available. Configuration-specific audit records remain protected by the Admin API.</p></div></div>';
  } else if (module.id === 'system') {
    byId('moduleContent').innerHTML = renderSystem();
  } else {
    byId('moduleContent').innerHTML = renderRecords(records.filter(item => item.domain === module.domain));
  }
  renderNavigation();
}

async function loadConfigurations({ keepContent = false } = {}) {
  if (!keepContent) setView('loadingState');
  const refresh = byId('refreshButton'); refresh.disabled = true; refresh.textContent = 'Refreshing…';
  try {
    const payload = await adminRequest(); records = Array.isArray(payload.items) ? payload.items : [];
    authorised = true;
    byId('accessStatus').textContent = 'Administrator access'; setView('consoleView'); renderModule();
    announce(`Configuration status loaded. ${records.length} record${records.length === 1 ? '' : 's'} available.`);
  } catch (error) {
    authorised = false;
    if (error.status === 401 || error.status === 403) {
      byId('unauthorisedMessage').textContent = error.status === 401 ? 'Authentication is required. Supply an administrator session before opening this console.' : 'Your authenticated role does not include Admin Console access.';
      setView('unauthorisedState'); byId('moduleNavigation').innerHTML = ''; byId('accessStatus').textContent = 'Access denied';
    } else {
      byId('errorMessage').textContent = `${error.message} ${error.code ? `Error: ${error.code}.` : ''}`;
      byId('requestId').textContent = error.requestId ? `Request ID: ${error.requestId}` : '';
      setView('errorState');
    }
    announce(error.message);
  } finally { refresh.disabled = false; refresh.textContent = 'Refresh status'; }
}

function setMenu(open) {
  document.body.classList.toggle('menu-open', open); byId('menuButton').setAttribute('aria-expanded', String(open)); byId('backdrop').hidden = !open;
  byId('sidebar').inert = !open && matchMedia('(max-width: 800px)').matches;
  byId('mainContent').inert = open;
  if (open) byId('sidebar').querySelector('a')?.focus();
}

addEventListener('hashchange', () => { activeModule = moduleFromLocation(); renderModule(); setMenu(false); byId('mainContent').focus(); });
byId('refreshButton').addEventListener('click', () => loadConfigurations({ keepContent: true }));
byId('retryButton').addEventListener('click', () => loadConfigurations());
byId('menuButton').addEventListener('click', () => setMenu(!document.body.classList.contains('menu-open')));
byId('backdrop').addEventListener('click', () => { setMenu(false); byId('menuButton').focus(); });
addEventListener('keydown', event => {
  if (!document.body.classList.contains('menu-open')) return;
  if (event.key === 'Escape') { setMenu(false); byId('menuButton').focus(); return; }
  if (event.key !== 'Tab') return;
  const links = [...byId('sidebar').querySelectorAll('a[href]')];
  if (!links.length) return;
  const first = links[0]; const last = links.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
matchMedia('(max-width: 800px)').addEventListener('change', event => { byId('sidebar').inert = event.matches; if (!event.matches) setMenu(false); });
byId('sidebar').inert = matchMedia('(max-width: 800px)').matches;
loadConfigurations();
