import json, pathlib, subprocess, tempfile, sys

def run(args, cwd=None):
 try:
  return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()
 except subprocess.CalledProcessError as exc:
  print(exc.output); raise
with tempfile.TemporaryDirectory(prefix='git-pin-test-') as root:
 root=pathlib.Path(root); lib=root/'library'; lib.mkdir()
 (lib/'setup.py').write_text("from setuptools import setup\nsetup(name='pin-probe',version='0.1.0',py_modules=['pin_probe'])\n")
 run(['git','init',str(lib)])
 run(['git','config','user.email','test@example.invalid'],lib)
 run(['git','config','user.name','Pin test'],lib)
 shas=[]
 for marker in ['first','second']:
  (lib/'pin_probe.py').write_text(f'MARKER={marker!r}\n')
  run(['git','add','.'],lib); run(['git','commit','-m',marker],lib)
  shas.append(run(['git','rev-parse','HEAD'],lib))
 run([sys.executable,'-m','venv',str(root/'venv')])
 python=str(root/'venv/bin/python')
 run([python,'-m','pip','install','wheel'])
 for sha, marker in zip([*shas, shas[0]],['first','second','first']):
  req=root/'requirements.txt'; req.write_text(f'pin-probe @ git+file://localhost{lib}@{sha}\n')
  run([python,'-m','pip','install','--upgrade','--force-reinstall','-r',str(req)])
  result=json.loads(run([python,'-c',"import pin_probe,json,importlib.metadata as m; print(json.dumps([pin_probe.MARKER,json.loads(m.distribution('pin-probe').read_text('direct_url.json'))['vcs_info']['commit_id']]))"]))
  assert result==[marker,sha], {'actual': result, 'expected': [marker,sha]}
 print('PASS: pip installs changed Git SHA with unchanged package version using install --upgrade --force-reinstall -r')
