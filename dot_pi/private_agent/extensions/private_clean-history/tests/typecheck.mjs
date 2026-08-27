import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const core=process.env.PI_PACKAGE_ROOT || resolve(dirname(process.execPath),'../lib/node_modules/@earendil-works/pi-coding-agent');
const dir=mkdtempSync(join(tmpdir(),'clean-history-typecheck-'));
try {
  const config={compilerOptions:{
    target:'es2023',module:'esnext',moduleResolution:'bundler',strict:true,
    noEmit:true,skipLibCheck:true,allowImportingTsExtensions:true,
    types:['node'],typeRoots:[`${core}/node_modules/@types`],
    paths:{
      '@earendil-works/pi-coding-agent':[`${core}/dist/index.d.ts`],
      '@earendil-works/pi-ai':[`${core}/node_modules/@earendil-works/pi-ai/dist/index.d.ts`],
      '@earendil-works/pi-tui':[`${core}/node_modules/@earendil-works/pi-tui/dist/index.d.ts`],
    },
  },files:['index.ts','model.ts','view.ts'].map(name=>join(root,name))};
  const path=join(dir,'tsconfig.json');writeFileSync(path,JSON.stringify(config));
  const result=spawnSync('tsc',['--project',path],{stdio:'inherit'});
  if(result.error)throw result.error;
  process.exitCode=result.status ?? 1;
} finally { rmSync(dir,{recursive:true,force:true}); }
