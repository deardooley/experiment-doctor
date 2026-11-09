import {readFile, writeFile} from 'node:fs/promises';
import {compile} from 'json-schema-to-typescript';

const source = new URL('../src/generated/contracts.schema.json', import.meta.url);
const target = new URL('../src/generated/contracts.ts', import.meta.url);
const generated = await compile(JSON.parse(await readFile(source, 'utf8')), 'BrowserContracts', {
  bannerComment: '/* Generated from packages/contracts/presentation.py. Do not edit. */',
  additionalProperties: false,
  style: {singleQuote: true, semi: true},
});
if (process.argv.includes('--check')) {
  if (await readFile(target, 'utf8').catch(() => '') !== generated) {
    throw new Error('Browser contracts drifted. Run the Python exporter, then npm run contracts.');
  }
} else await writeFile(target, generated);
