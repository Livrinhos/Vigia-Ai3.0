"""Integra o ZIP Performance autorizado no computador, sem republicar ou sobrescrever a base."""
import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

EXPECTED_SOURCE_SHA256='c880a33acf7109924a939e75b42da1e6cac820b7ab9ec6d75054a17c426a539d'


def integrate(archive,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('A base já existe. Uma nova versão deve ser extraída em outra pasta; nada será sobrescrito.')
    h=hashlib.sha256()
    with Path(archive).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    if h.hexdigest()!=EXPECTED_SOURCE_SHA256:raise ValueError('O ZIP não corresponde ao pacote Performance revisado. Use o arquivo original entregue, sem recompactar ou modificar.')
    entries={}
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            p=PurePosixPath(info.filename.replace('\\','/'))
            if p.is_absolute() or '..' in p.parts or ':' in str(p) or stat.S_ISLNK(info.external_attr>>16):raise ValueError('ZIP de base inválido.')
            parts=list(p.parts)
            if parts and parts[0]=='VigiaAI-Performance':parts=parts[1:]
            if not parts or info.is_dir():continue
            rel='/'.join(parts)
            if rel in entries:raise ValueError('Caminho duplicado no ZIP.')
            entries[rel]=info
        required=['main.py','epi_monitoramento.py','epi_inferencia.py','performance_runtime.py','presentation_mode.py','performance/models-origin.json']
        if any(n not in entries for n in required):raise ValueError('Selecione o ZIP VigiaAI-Performance entregue anteriormente.')
        manifest=json.loads(z.read(entries['performance/models-origin.json']).decode('utf-8-sig'))
        for item in manifest:
            rel=item['path'].replace('\\','/')
            if rel not in entries or hashlib.sha256(z.read(entries[rel])).hexdigest()!=item['sha256']:
                raise ValueError('Hash do peso diverge do inventário Performance: '+rel)
        size=sum(i.file_size for i in entries.values())
        if size>256*1024*1024:raise ValueError('ZIP da base acima do tamanho esperado.')
        destination.mkdir(parents=True,exist_ok=False)
        weights={i['path'].replace('\\','/') for i in manifest}
        allowed={'.py','.html','.css','.js','.mjs','.json','.yaml','.yml','.txt','.md','.ps1','.cmd'}
        for rel,info in entries.items():
            p=PurePosixPath(rel)
            if rel not in weights and p.suffix.lower() not in allowed:continue
            if any(part in ('.git','.env','capturas','amostras_epi','dados_privados','backups','diagnosticos') for part in p.parts):continue
            target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(info))
        (destination/'performance/ISOLATED_COPY').write_text('Base privada integrada localmente; fonte e pesos preservados.',encoding='utf-8')
    return destination


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zip',type=Path,required=True)
    p.add_argument('--destination',type=Path,default=Path(__file__).resolve().parent/'.performance-base')
    a=p.parse_args();print(integrate(a.zip,a.destination))
