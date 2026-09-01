import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const page = await readFile(new URL('../employee/index.html', import.meta.url), 'utf8');
const normalizedPage = page.replaceAll('\r\n', '\n');

assert.match(normalizedPage, /data-detail-tab="conversation"/, 'Conversation must be a claim-detail tab.');
assert.match(normalizedPage, /data-detail-page="conversation"/, 'Conversation must render inside claim detail.');
assert.match(
  normalizedPage,
  /function openCustomerChat[\s\S]*?selectClaimDetailTab\('conversation'\)/,
  'The conversation entry point must select the claim-detail tab.',
);
assert.doesNotMatch(normalizedPage, /id="customerChatView"/, 'Conversation must not create a separate page.');
assert.doesNotMatch(normalizedPage, /window\.history\.(pushState|back)/, 'Conversation must not change page history.');
assert.match(
  normalizedPage,
  /id="customerChatReplyTitle">Ask or reply to claimant</,
  'The shared handoff composer must clearly support claimant questions.',
);
assert.match(
  normalizedPage,
  /id="customerChatText"[^>]+aria-label="Question or message to claimant"/,
  'The claimant question control must have a clear accessible name.',
);
