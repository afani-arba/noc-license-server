const fs = require('fs');
const parser = require('@babel/parser');
const file = fs.readFileSync('e:/noc-sentinel-v3/frontend/src/pages/BillingPage.jsx', 'utf8');
try {
  parser.parse(file, { sourceType: 'module', plugins: ['jsx'] });
  console.log('No syntax error found by Babel');
} catch (e) {
  console.log('Syntax error:', e.message, 'at line:', e.loc.line, 'col:', e.loc.column);
}
