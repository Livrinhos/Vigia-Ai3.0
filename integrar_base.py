"""Compatibilidade com os comandos antigos; a instalação atual não recebe ZIP externo."""
import argparse
from pathlib import Path
from preparar_instalacao import ROOT, prepare


def integrate(archive=None,destination=None):
    if destination is not None and Path(destination).resolve() != (ROOT/'performance').resolve():
        raise ValueError('As duas versões já fazem parte deste projeto. Execute Instalar.cmd na raiz, sem selecionar outra pasta.')
    if archive is not None:
        print('Não é mais necessário selecionar ZIP: o código completo está neste repositório.',flush=True)
    return Path(prepare()['base'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zip',type=Path,required=False)
    p.add_argument('--destination',type=Path)
    args=p.parse_args()
    try:print(integrate(args.zip,args.destination))
    except (OSError,ValueError,RuntimeError) as error:p.exit(1,str(error)+'\n')
