"""Inventário e backup locais. Nunca escreve na origem; não carrega pesos pickle."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

SKIP = {'.git', '.venv', 'venv', 'env', '__pycache__', '.pytest_cache', 'node_modules'}


def sha256(file):
    h = hashlib.sha256()
    with Path(file).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def outside(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Origem e destino precisam ser diretórios separados, sem sobreposição.')
    return source, destination


def inventory(source):
    source = Path(source).resolve()
    if not source.is_dir():
        raise ValueError('Pasta de origem inexistente.')
    files, skipped = [], []
    for folder, dirs, names in os.walk(source, followlinks=False):
        for name in list(dirs):
            p = Path(folder) / name
            if name in SKIP or p.is_symlink() or p.is_junction():
                dirs.remove(name)
                skipped.append(str(p.relative_to(source)))
        for name in sorted(names):
            p = Path(folder) / name
            rel = p.relative_to(source).as_posix()
            if p.is_symlink():
                skipped.append(rel)
                continue
            stat = p.stat()
            digest = sha256(p)
            after = p.stat()
            if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError('Arquivo mudou durante o inventário: ' + rel)
            files.append(dict(path=rel, bytes=stat.st_size, sha256=digest,
                              model=p.suffix.lower() in {'.pt', '.pth', '.onnx', '.engine'},
                              sensitive=name.startswith('.env') or p.suffix.lower() in {'.jpg','.jpeg','.png','.mp4','.db'},
                              modified_ns=stat.st_mtime_ns))
    return dict(source=str(source), files=files, skipped=skipped,
                note='Contém caminhos privados; manter local. Links/junctions e ambientes excluídos exigem revisão.')


def verify(source, manifest):
    root = Path(source).resolve()
    failures = []
    for item in manifest['files']:
        p = (root / item['path']).resolve()
        if not p.is_relative_to(root) or not p.is_file() or sha256(p) != item['sha256']:
            failures.append(item['path'])
    return failures


def copy_verified(source, destination, manifest):
    source, destination = outside(source, destination)
    if destination.exists():
        raise ValueError('Destino já existe; escolha uma pasta nova para evitar sobrescritas.')
    destination.mkdir(parents=True)
    for item in manifest['files']:
        src, dst = (source / item['path']).resolve(), (destination / item['path']).resolve()
        if not src.is_relative_to(source) or not dst.is_relative_to(destination):
            raise ValueError('Caminho fora da raiz.')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    failures = verify(destination, manifest) + verify(source, manifest)
    if failures:
        raise RuntimeError('Backup incompleto ou origem mudou; NÃO restaurar: ' + ', '.join(failures))
    return destination


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['inventory', 'backup', 'restore', 'compare'])
    p.add_argument('source', type=Path)
    p.add_argument('--destination', type=Path, required=True)
    p.add_argument('--manifest', type=Path)
    a = p.parse_args()
    outside(a.source, a.destination)
    if a.action in ('backup', 'restore'):
        manifest = json.loads(a.manifest.read_text(encoding='utf-8-sig')) if a.manifest else inventory(a.source)
        if verify(a.source, manifest):
            raise RuntimeError('Origem não corresponde ao inventário. Nenhum arquivo copiado.')
        dest = copy_verified(a.source, a.destination, manifest)
        if a.action == 'backup':
            # Referência Git é somente leitura; bundle é histórico, pode conter segredos antigos.
            if (a.source / '.git').exists():
                r = subprocess.run(['git','-C',str(a.source),'bundle','create',str(dest / 'LOCAL-HISTORY.bundle'),'--all'], capture_output=True)
                manifest['git_bundle_ok'] = r.returncode == 0
            env = a.source / '.venv' / 'Scripts' / 'python.exe'
            if env.is_file():
                r = subprocess.run([str(env), '-m', 'pip', 'freeze'], capture_output=True, text=True, timeout=60)
                (dest / 'LOCAL-ENVIRONMENT.txt').write_text(r.stdout, encoding='utf-8')
        (dest / 'LOCAL-MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print('Cópia verificada em:', dest)
        return
    if a.destination.exists():
        raise ValueError('Saída já existe; escolha outro nome.')
    manifest = inventory(a.source)
    if a.action == 'compare':
        baseline = json.loads((Path(__file__).parent / 'performance/source-files.json').read_text(encoding='utf-8-sig'))
        old = {v['path']: v['sha256'] for v in baseline['files']}
        current = {v['path']: v['sha256'] for v in manifest['files']}
        manifest['comparison'] = dict(commit=baseline['commit'],
            changed=[k for k in old.keys() & current.keys() if old[k] != current[k]],
            missing=sorted(old.keys() - current.keys()), local_only=sorted(current.keys() - old.keys()))
    a.destination.parent.mkdir(parents=True, exist_ok=True)
    a.destination.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Inventário local salvo em:', a.destination)


if __name__ == '__main__':
    main()
