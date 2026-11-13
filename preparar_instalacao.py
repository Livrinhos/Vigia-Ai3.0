"""Prepara as duas versões sem seleção de ZIP; pesos originais verificados por SHA-256."""
import argparse
import hashlib
import json
import os
import shutil
import ssl
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SOURCE_COMMIT='e1d054ef33ea1fd007d31ed9c96440327f81859f'
MODELS=[
    dict(path='yolov8n.pt',bytes=6549796,sha256='f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36'),
    dict(path='epi.pt',bytes=6246435,sha256='1f9fdde980c2e56c22c8857b778b5213fb07fc21fbcdb05fe71ef9c1fb50ce0e'),
    dict(path='runs/detect/treinamento_epi-2/weights/best.pt',bytes=6257251,sha256='eeac8b62d3d78052c736981dd7ad1554a8902ff179b5543d1706f35c9d221bf5'),
]


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def valid(path,item):
    return path.is_file() and path.stat().st_size==item['bytes'] and file_hash(path)==item['sha256']


def prepare(root=ROOT,download=True,opener=urllib.request.urlopen):
    root=Path(root).resolve();base=root/'performance'
    required=['main.py','epi_inferencia.py','epi_monitoramento.py','queda_temporal.py','runtime_ia.py',
              'performance_runtime.py','presentation_mode.py','requirements.txt','requirements-cpu.txt','requirements-cuda.txt']
    if any(not (base/p).is_file() for p in required):
        raise ValueError('O código Performance não está completo. Baixe novamente o ZIP da branch atual e extraia tudo em uma pasta nova.')
    result=[]
    for item in MODELS:
        target=base/item['path']
        if target.exists():
            if not valid(target,item):
                raise ValueError('Há um peso diferente em '+str(target)+'. Ele foi preservado. Use uma pasta nova para esta instalação.')
            print('Modelo preservado e verificado: '+item['path'],flush=True)
            result.append(dict(path=item['path'],status='existing'));continue
        # Reaproveita a cópia anterior somente quando os bytes correspondem ao original.
        legacy=root/'.performance-base'/item['path']
        target.parent.mkdir(parents=True,exist_ok=True)
        if valid(legacy,item):
            with legacy.open('rb') as source,target.open('xb') as dest:shutil.copyfileobj(source,dest)
            print('Modelo copiado da versão anterior, sem modificá-la: '+item['path'],flush=True)
            result.append(dict(path=item['path'],status='copied'));continue
        if not download:raise FileNotFoundError('Modelo original ausente: '+item['path'])
        urls=[f'https://raw.githubusercontent.com/susuque-samuel/VigiaAi/{SOURCE_COMMIT}/{item["path"]}',
              f'https://github.com/susuque-samuel/VigiaAi/raw/{SOURCE_COMMIT}/{item["path"]}']
        failures=[]
        for url in urls:
            temporary=target.with_name('.download-'+uuid.uuid4().hex+'.part')
            print('Baixando automaticamente '+item['path']+'…',flush=True)
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'VigiaAI-Installer/3.0'})
                with opener(req,timeout=45) as response,temporary.open('xb') as f:
                    size=0
                    while block:=response.read(1024*1024):
                        size+=len(block)
                        if size>item['bytes']:raise ValueError('O servidor enviou tamanho inesperado.')
                        f.write(block)
                if not valid(temporary,item):raise ValueError('O download não passou na verificação SHA-256.')
                # Nunca substitui um peso existente, nem mesmo em uma corrida entre instaladores.
                with temporary.open('rb') as source,target.open('xb') as dest:shutil.copyfileobj(source,dest)
                result.append(dict(path=item['path'],status='downloaded'));break
            except FileExistsError:raise ValueError('Um arquivo apareceu durante a instalação e foi preservado. Execute novamente para verificar.')
            except (OSError,ValueError,urllib.error.URLError) as e:failures.append(str(e))
        else:
            raise RuntimeError('Não foi possível baixar '+item['path']+'. Confira a internet/acesso ao GitHub. Nenhum peso existente foi alterado. '+ '; '.join(failures))
    # O código já está no repositório. O marcador apenas identifica a instalação separada.
    marker=base/'performance/ISOLATED_COPY';marker.parent.mkdir(parents=True,exist_ok=True)
    if not marker.exists():marker.write_text('Duas versões no mesmo projeto; modelos originais verificados.',encoding='utf-8')
    return dict(base=str(base),versions=['Performance','3.0'],models=result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(prepare(download=not args.check_only),ensure_ascii=False,indent=2))
    except (OSError,ValueError,RuntimeError) as error:parser.exit(1,str(error)+'\n')
