#!/usr/bin/env node
// Read-only access to the unmodified Design -isms snapshot. No network or dependencies.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const upstream = path.join(root, 'assets/upstream');
const data = name => JSON.parse(fs.readFileSync(path.join(upstream, 'assets/data', `${name}.json`), 'utf8'));
const domains = ['isms', 'effects', 'color', 'typography', 'layout', 'motion'];
const site = 'https://lidge-jun.github.io/design-isms/';
const args = process.argv.slice(2);
const command = args.shift();
const options = {};
const positional = [];
for (let i = 0; i < args.length; i++) {
  if (args[i].startsWith('--')) {
    const key = args[i].slice(2);
    if (!['query', 'limit', 'variant', 'project', 'mood', 'brightness'].includes(key)) fail(`Unknown option: ${key}`);
    if (!args[i + 1] || args[i + 1].startsWith('--')) fail(`Missing value: ${key}`);
    options[key] = args[++i];
  } else positional.push(args[i]);
}
function fail(message) { console.error(message); process.exit(1); }
function print(value) { console.log(JSON.stringify(value, null, 2)); }
function records(domain) { if (!domains.includes(domain)) fail(`Domain must be: ${domains.join(', ')}`); return data(domain); }
function find(domain, id) { const item = records(domain).find(x => x.id === id); if (!item) fail(`Unknown ${domain} id: ${id}`); return item; }
function original(domain, item) {
  const page = domain === 'isms' ? '' : `${domain}.html`;
  const files = domain === 'isms' ? item.images : [{file: item.guide.file, label: item.guide.alt}];
  const folder = domain === 'isms' ? item.id : `${domain}/${item.id}`;
  return {source: `${site}${page}#${item.id}`, images: files.map(image => {
    const absolute = path.join(upstream, 'assets/images', folder, image.file);
    if (!fs.existsSync(absolute)) fail(`Missing original image: ${absolute}`);
    return {file: image.file, label: image.label, absolute, url: `${site}assets/images/${folder}/${image.file}`};
  })};
}
function compact(domain, item) {
  return {id: item.id, name: item.name, nameKr: item.nameKr,
    kind: item.kind, keywords: item.keywords, category: item.category,
    ...original(domain, item)};
}

switch (command) {
  case 'stats': {
    const manifest = JSON.parse(fs.readFileSync(path.join(root, 'references/source-manifest.json')));
    print({commit: manifest.commit, date: manifest.retrieved_date,
      files: manifest.file_count, bytes: manifest.bytes,
      catalogs: Object.fromEntries(domains.map(d => [d, records(d).length])),
      originals: manifest.files.filter(f => f.path.endsWith('.png')).length,
      previews: manifest.files.filter(f => f.path.endsWith('.webp')).length});
    break;
  }
  case 'list': {
    const domain = positional[0] || 'isms';
    const query = (options.query || '').toLowerCase();
    const limit = options.limit === undefined ? 10 : Number(options.limit);
    if (!Number.isInteger(limit) || limit < 1) fail('limit must be a positive integer');
    const items = records(domain).filter(x => JSON.stringify(x).toLowerCase().includes(query));
    print({domain, total: items.length, order: 'upstream source order', items: items.slice(0, limit).map(x => compact(domain, x))});
    break;
  }
  case 'show': {
    const [domain, id] = positional;
    const item = find(domain, id);
    const result = {record: item, ...original(domain, item)};
    if (domain === 'isms') result.devGuide = data('dev-guides')[id];
    if (domain === 'effects') {
      result.documentation = data('effects-docs')[id];
      const snippets = data('effects-snippets').snippets;
      result.snippet = Array.isArray(snippets) ? snippets.find(x => x.id === id) : snippets[id];
    }
    print(result);
    break;
  }
  case 'recommend': {
    const answers = {};
    const config = data('finder-config');
    for (const q of config.questions) {
      if (options[q.id] !== undefined) {
        if (!q.options.some(x => x.id === options[q.id])) fail(`Invalid ${q.id}; choose ${q.options.map(x => x.id).join(', ')}`);
        answers[q.id] = options[q.id];
      }
    }
    const context = vm.createContext({});
    for (const filename of ['app-export.js', 'finder.js']) {
      vm.runInContext(fs.readFileSync(path.join(upstream, 'assets/js', filename), 'utf8'), context, {filename, timeout: 2000});
    }
    const results = context.DesignFinder.score(data('isms'), data('dev-guides'), config, answers);
    print({method: 'Unmodified upstream DesignFinder.score', answers,
      note: Object.keys(answers).length ? 'Only explicitly supplied criteria were scored.' : 'No criteria: first three style entries in upstream order.',
      results: results.map(result => ({...result, ...original('isms', find('isms', result.id))}))});
    break;
  }
  case 'preview': {
    const [domain, ...ids] = positional;
    if (!ids.length) fail('Usage: preview DOMAIN ID [ID ...] [--variant landing.png]');
    // Resolve all entries before emitting output: invalid variants never silently fall back.
    const selected = ids.map(id => {
      const item = find(domain, id);
      const ref = original(domain, item);
      const image = options.variant ? ref.images.find(x => x.file === options.variant) : ref.images[0];
      if (!image) fail(`No variant ${options.variant} for ${id}; available: ${ref.images.map(x => x.file).join(', ')}`);
      return {item, ref, image};
    });
    for (const {item, ref, image} of selected) {
      console.log(`**${item.name} — ${image.label}** · [원본](${ref.source})\n`);
      console.log(`![${item.name} 원본](<${image.absolute}>)\n`);
    }
    break;
  }
  default:
    fail('Usage: catalog.mjs stats | list DOMAIN [--query TEXT] [--limit N] | show DOMAIN ID | recommend [--project ID] [--mood ID] [--brightness ID] | preview DOMAIN ID [ID ...] [--variant FILE]');
}
