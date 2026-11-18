/* ===========================================================================
   Copilot answer renderer (tools/ui_verification/verify_copilot_render.js)

   WHY THIS EXISTS
   ---------------
   The dashboard (`dashboard.js`) carries a trimmed-down markdown renderer for
   copilot answers. It once skipped its inline pass on bullet lines, and nearly
   every bullet the copilot writes wraps its label in **bold** ("- **Current
   Bias**: …"), so most answers reached the reader as literal asterisks. The
   classic terminal's copy (now deleted with /classic) also injected unescaped
   markup. Neither fault was visible to the HTTP layer.

   WHAT IT CHECKS
   --------------
   It extracts `esc` / `copilotInline` / `copilotHtml` by name, EVALUATES them,
   and asserts:
     1. hostile input is escaped — no raw tag survives;
     2. bullets and bold render, and no `**` reaches the reader;
     3. the copilot panel renders the answer through `copilotHtml`.

   Run:  node tools/ui_verification/verify_copilot_render.js
   Exits non-zero if any check fails. No server, no browser.
   =========================================================================== */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const DASHBOARD = path.join(ROOT, 'jarvis/ui/static/js/dashboard.js');

let checks = 0;
let failures = 0;
function ok(label, condition, detail) {
  checks++;
  if (condition) {
    console.log('  PASS  ' + label);
  } else {
    failures++;
    console.log('  FAIL  ' + label + (detail ? '  -> ' + detail : ''));
  }
}

/* Pull `function <name>(…) { … }` out of a file by matching braces. Safe here
   because none of these three bodies contains a brace inside a string, template
   literal or regex. */
function extractFunction(src, name) {
  const at = src.indexOf('function ' + name + '(');
  if (at < 0) return null;
  const open = src.indexOf('{', at);
  if (open < 0) return null;
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const ch = src[i];
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) return src.slice(at, i + 1);
    }
  }
  return null;
}

const src = fs.readFileSync(DASHBOARD, 'utf8');
const names = ['esc', 'copilotInline', 'copilotHtml'];
const bodies = names.map((n) => extractFunction(src, n));
const missing = names.filter((n, i) => !bodies[i]);
if (missing.length) throw new Error('dashboard.js is missing: ' + missing.join(', '));
const api = new Function(bodies.join('\n') + '\nreturn { copilotHtml: copilotHtml };')();

console.log('copilot answer renderer\n');

const HOSTILE = '<img src=x onerror=alert(1)> & "quoted"';
const ANSWER = [
  '**Open positions — 1**',
  '- **Current Bias**: BULL (TREND_FOLLOW)',
  '- Balance **1,234.56** · Equity **1,240.00**',
  'Ask me about a symbol with *emphasis*.'
].join('\n');

console.log('escaping');
let out = api.copilotHtml(HOSTILE);
ok('a tag in the text is escaped, not injected',
  out.indexOf('<img') < 0 && out.indexOf('&lt;img') >= 0, out.slice(0, 160));
ok('quotes and ampersands are escaped',
  out.indexOf('&quot;') >= 0 && out.indexOf('&amp;') >= 0, out.slice(0, 160));
ok('the escaped text keeps its words',
  out.indexOf('onerror=alert(1)') >= 0, out.slice(0, 160));

console.log('\nmarkdown');
out = api.copilotHtml(ANSWER);
ok('bold inside a bullet is rendered',
  out.indexOf('<b>Current Bias</b>') >= 0 && out.indexOf('<b>1,234.56</b>') >= 0, out.slice(0, 200));
ok('no raw asterisks reach the reader', out.indexOf('**') < 0, out.slice(0, 200));
ok('the bullets form one list of two items',
  (out.match(/<ul>/g) || []).length === 1 && (out.match(/<li>/g) || []).length === 2, out.slice(0, 200));
ok('a bold line outside a list is still bold', out.indexOf('<b>Open positions') >= 0, out.slice(0, 200));
ok('single asterisks are emphasised', out.indexOf('<i>emphasis</i>') >= 0, out.slice(0, 200));

console.log('\ncall sites');
ok('the dashboard renders the answer through copilotHtml', src.indexOf('copilotHtml(text ||') >= 0, '');

console.log('\n' + (failures === 0
  ? 'all ' + checks + ' checks passed'
  : failures + ' of ' + checks + ' checks FAILED'));
process.exit(failures === 0 ? 0 : 1);
