import { basename } from 'node:path';

const agent = process.env.npm_config_user_agent;
const executable = basename(process.env.npm_execpath ?? '');
const isPnpm = agent?.startsWith('pnpm/') || /^pnpm(?:\.(?:c?js|exe))?$/.test(executable);

if (!isPnpm) {
  console.error('This repository uses pnpm. Run pnpm install from the repository root.');
  process.exit(1);
}
