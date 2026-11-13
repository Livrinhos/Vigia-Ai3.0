"""Compara medições reais; não transforma concordância com a base em precisão."""
import argparse
import json
from collections import Counter
from pathlib import Path
from avaliar_eventos import avaliar


def readings(folder):
    states=Counter(); people=0; frames=0
    with (folder/'readings.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line);frames+=1;people+=len(row['pessoas'])
            for person in row['pessoas']:
                states['postura:'+str(person.get('postura'))]+=1
                for epi,state in person.get('epis',{}).items():states[epi+':'+state]+=1
    return dict(frames=frames,pessoas_observadas=people,estados=dict(states))


def compare(before,after,reference=None):
    a=json.loads((before/'result.json').read_text());b=json.loads((after/'result.json').read_text())
    for key in ('video_id','duracao_segundos','models','policy','absence','device','warmup_frames'):
        if a[key]!=b[key]:raise ValueError('Comparação incompatível: '+key)
    if a['cold_summary']['frames']!=b['cold_summary']['frames']:
        raise ValueError('Quantidade de quadros incompatível.')
    fa,fb=a['summary']['fps_processamento'],b['summary']['fps_processamento']
    result=dict(fps_antes=fa,fps_depois=fb,ganho_percentual=(fb/fa-1)*100 if fa and fb else None,
                antes=a['summary'],depois=b['summary'],recursos_antes=a['resources'],recursos_depois=b['resources'],
                leituras_antes=readings(before),leituras_depois=readings(after),
                aprovada_para_apresentacao=False,
                motivo='Requer revisão de pessoas, capacetes, óculos, posturas e eventos contra anotações independentes. Contagens não medem precisão.')
    if reference:
        r=json.loads(reference.read_text(encoding='utf-8'))
        x,y=avaliar(r,a),avaliar(r,b)
        result.update(eventos_antes=x,eventos_depois=y)
        if y['perdidos']>x['perdidos'] or y['falsos_alertas']>x['falsos_alertas']:
            result['motivo']='REJEITAR: alertas perdidos ou falsos aumentaram. Não aprovar apenas pelo FPS.'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('before',type=Path);p.add_argument('after',type=Path)
    p.add_argument('--reference',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('Saída já existe.')
    a.output.write_text(json.dumps(compare(a.before,a.after,a.reference),indent=2),encoding='utf-8')
    print(a.output)
