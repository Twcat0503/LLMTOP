import { readFileSync, writeFileSync } from 'node:fs';

const metadata = JSON.parse(readFileSync(new URL('../frontend/package.json', import.meta.url), 'utf8'));
const output = new URL('../src/llmtop/web_static/', import.meta.url);
readFileSync(new URL('index.html', output));
writeFileSync(new URL('build-info.json', output), JSON.stringify({ version: metadata.version }) + '\n');
writeFileSync(new URL('.gitkeep', output), '');
