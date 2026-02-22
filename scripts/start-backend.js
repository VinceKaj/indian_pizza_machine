const path = require('path');
const { spawn } = require('child_process');

const root = path.resolve(__dirname, '..');
const backend = path.join(root, 'backend');
const isWin = process.platform === 'win32';
const venvPython = path.join(backend, isWin ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const fs = require('fs');

if (!fs.existsSync(venvPython)) {
  console.error('Backend venv not found. From the project root run:');
  console.error('  cd backend');
  console.error('  python -m venv .venv');
  console.error(isWin ? '  .venv\\Scripts\\activate' : '  source .venv/bin/activate');
  console.error('  pip install -r requirements.txt');
  process.exit(1);
}

const child = spawn(venvPython, ['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '0.0.0.0', '--port', '9000'], {
  cwd: backend,
  stdio: 'inherit',
  shell: false,
});

child.on('error', (err) => {
  console.error(err);
  process.exit(1);
});
child.on('exit', (code) => process.exit(code ?? 0));
