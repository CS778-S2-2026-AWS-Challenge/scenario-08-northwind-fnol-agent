import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const page = await readFile(new URL('../employee/index.html', import.meta.url), 'utf8');
const normalizedPage = page.replaceAll('\r\n', '\n');
const workbenchUrl = normalizedPage.match(/function workbenchUrl\(\) \{[\s\S]*?\n    \}/)?.[0];
const setView = normalizedPage.match(/function setView\(view,[\s\S]*?\n    \}\n\n    function restoreViewFromHistory/)?.[0]
  ?.replace('\n\n    function restoreViewFromHistory', '');

assert.ok(workbenchUrl, 'The workbench URL helper must exist.');
assert.ok(setView, 'The view navigation function must exist.');

function createNavigation({ hash, entryCreated = false }) {
  const navigation = { backCalls: 0, replaceCalls: 0, pushCalls: 0 };
  const classes = new Map();
  const window = {
    location: { hash, pathname: '/employee/index.html', search: '' },
    history: {
      back() { navigation.backCalls += 1; },
      pushState(_state, _title, nextHash) {
        navigation.pushCalls += 1;
        window.location.hash = nextHash;
      },
      replaceState(_state, _title, nextUrl) {
        navigation.replaceCalls += 1;
        window.location.hash = '';
        navigation.replacedUrl = nextUrl;
      },
    },
  };
  const workbenchView = { hidden: true };
  const customerChatView = { hidden: false };
  const byId = id => ({
    classList: {
      toggle(_name, active) { classes.set(id, active); },
    },
  });
  const execute = new Function(
    'window',
    'workbenchView',
    'customerChatView',
    'byId',
    'renderCustomerChat',
    `${entryCreated ? 'let customerChatHistoryEntryCreated = true;' : 'let customerChatHistoryEntryCreated = false;'}\n${workbenchUrl}\n${setView}\nreturn setView;`,
  );
  return {
    navigation,
    setView: execute(window, workbenchView, customerChatView, byId, () => {}),
    views: { workbenchView, customerChatView },
    window,
  };
}

for (const trigger of ['Workbench navigation', 'Customer chat Back button']) {
  const directLoad = createNavigation({ hash: '#customer-chat' });
  directLoad.setView('workbench');

  assert.equal(directLoad.navigation.backCalls, 0, `${trigger} must not leave a direct chat URL`);
  assert.equal(directLoad.navigation.replaceCalls, 1);
  assert.equal(directLoad.window.location.hash, '');
  assert.equal(directLoad.views.workbenchView.hidden, false);
  assert.equal(directLoad.views.customerChatView.hidden, true);
}

const inAppEntry = createNavigation({ hash: '#customer-chat', entryCreated: true });
inAppEntry.setView('workbench');
assert.equal(inAppEntry.navigation.backCalls, 1, 'An in-app chat entry should return through history.');
assert.equal(inAppEntry.navigation.replaceCalls, 0);
