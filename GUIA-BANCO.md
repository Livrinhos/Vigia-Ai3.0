# Banco de Imagens e Treinamento — guia de uso

Instalação: veja o README da raiz. As duas versões agora fazem parte do repositório.

## Importar as fotos que vocês já têm

Na página **Banco de Imagens e Treinamento**:

1. Informe um nome de sessão, por exemplo “Câmera feira — manhã”.
2. Informe o **mesmo grupo de origem** para imagens da mesma pessoa, gravação ou sequência,
   mesmo que sejam importadas em momentos diferentes. Isso evita vazamento entre treino e teste.
3. Confirme que pode usar essas fotos.
4. Escolha fotos individuais/múltiplas, um ZIP ou **Importar pasta local**.
   Você pode selecionar diretamente `amostras_epi/pendentes` no computador antigo.

As fotos são enviadas em blocos de até 4 MB. O conteúdo é decodificado e validado; o nome
ou extensão não basta. Limites: 20 MB por imagem, 32 milhões de pixels, 512 MB por arquivo
ZIP, 5.000 imagens e 1 GB descompactado por ZIP. ZIPs com caminhos de fuga, links,
criptografia, arquivos executáveis, arquivos aninhados ou expansão excessiva são rejeitados.
O ZIP nunca é extraído usando seus próprios caminhos no disco.

JPG/JPEG, PNG e WebP estáticos são aceitos. Inclua `.txt` YOLO e JSON correspondentes na
pasta/ZIP. A estrutura `images/train/a.jpg` + `labels/train/a.txt` também é reconhecida.
Um `data.yaml` fornecido deve declarar exatamente as cinco classes originais:

| Índice | Classe |
|---:|---|
| 0 | capacete |
| 1 | colete |
| 2 | oculos |
| 3 | luvas |
| 4 | mascara |

Anotações importadas ficam **pendentes**. Metadados de capturas não são convertidos em
verdade de treinamento. Duplicatas por bytes/pixels são reconhecidas sem criar outra cópia
da imagem; as origens e anotações alternativas são preservadas para revisão.
Imagens de um outro computador não estão automaticamente disponíveis: importe-as naquele PC
ou selecione uma cópia autorizada pelo navegador. O original nunca é apagado ou movido.

Se um envio falhar, os blocos já recebidos permanecem em `importacoes`. A API informa o
offset para clientes que retomem o envio; a interface pode iniciar uma nova importação,
e a deduplicação evita multiplicar fotos já recebidas. Arquivos incompletos não entram no dataset.

## Revisar e anotar

A galeria oferece pesquisa, sessão, paginação e filtros **Todas, Pendentes, Revisadas,
Aprovadas, Rejeitadas e Prontas para treino**. Abra uma imagem para ver dimensões, origens,
metadados, avisos, similares e anotações.

- Arraste para desenhar uma caixa; clique em uma caixa para selecionar, mudar rótulo ou remover.
  Para corrigir a geometria, remova e desenhe novamente.
- Marque objetos EPI com as classes acima. Regiões auxiliares de **pessoa** não mudam os IDs de EPI.
- Marque **regiões de cabeça** como `com_capacete`, `sem_capacete` ou `inconclusivo` para o
  conjunto de um classificador separado. Isso **não cria** uma caixa YOLO `no_helmet`.
- Uma imagem sem objeto EPI visível pode ter arquivo YOLO vazio somente após confirmação
  explícita de negativo revisado. Em um grupo com apenas um capacete, anote esse capacete
  e, se desejado, as cabeças individuais; não invente objetos onde há ausência.
- **Sugerir com IA** executa um detector local em processo separado. Nenhuma sugestão é
  automaticamente aceita; confirme as caixas e a revisão humana para aprovar.

Todas as revisões são versionadas. A aprovação exige confirmação humana e reconhecimento dos
avisos de qualidade. A visualização preserva a geometria dos pixels sem rotação EXIF silenciosa;
o download do original mantém seus bytes e metadados. Excluir da galeria leva à **lixeira
recuperável**, mediante confirmação; não apaga os arquivos. Aprovação em lote sem revisão individual
não é permitida. As anotações aprovadas podem ser exportadas em YOLO.

## Marcar várias imagens de uma vez

1. Encerre o monitoramento. Em **Treinamento da IA**, escolha o modelo inicial `epi.pt`
   e CPU ou CUDA disponível; esses campos também são usados pelas sugestões.
2. Na galeria, filtre por sessão e **Pendentes**. Use **Selecionar todas do filtro**
   (até 5.000 imagens, incluindo outras páginas) ou marque apenas as fotos desejadas.
3. Clique em **Sugerir marcações em lote**. Acompanhe o progresso e eventual cancelamento
   em **Trabalhos e resultados**. Uma instância do detector é reutilizada, processando
   uma imagem por vez para limitar memória. Nada é treinado ou aprovado nesse passo.
4. Ao terminar, clique em **Revisar selecionadas**. As sugestões aparecem no editor.
   Corrija caixas erradas e objetos que ficaram sem marcação; selecione **Aprovada**,
   confirme a revisão e os avisos e use **Salvar e próxima**. As confirmações não são
   copiadas para a foto seguinte. **Pular sem salvar** deixa a foto para outra revisão.
5. Prepare o dataset e inicie o treinamento somente depois da revisão.

O lote processa somente imagens pendentes sem caixas nem negativo confirmado. Fotos já
anotadas/revisadas são puladas, sem alteração. As sugestões ficam separadas no catálogo,
fora das anotações de treino. Edições concorrentes invalidam sugestões antigas. Se cancelar,
os resultados das imagens já concluídas continuam disponíveis; é possível processar uma nova
seleção depois. Falhas individuais aparecem no resultado do trabalho.

Uma foto sem detecções **não é aprovada nem marcada como negativo automaticamente**.
O detector atual sugere objetos EPI, sem criar uma classe `no_helmet` ou afirmar ausência
nas outras pessoas. Confira também os EPIs que ele deixou de detectar. Esta assistência
reduz o desenho manual, mas sua qualidade depende dos modelos preservados.

## Preparar dataset e iniciar treinamento

**Preparar dataset** usa somente imagens aprovadas. Une grupos de origem e imagens muito
semelhantes antes de separar treino/validação/teste. A divisão é por grupo, não por fotos aleatórias.
São necessários pelo menos 12 imagens aprovadas e três componentes independentes, com capacetes
em todas as divisões. Sem isso, a preparação é bloqueada com orientação.

A auditoria da base Performance é reutilizada. O snapshot contém imagens, labels, YAML,
manifesto de grupos/revisão/autorização e um selo SHA-256. Alterações posteriores invalidam o
snapshot; revisões novas exigem preparar outro dataset. Não há substituição de snapshots antigos.

Para comparar modelos, confirme também que os grupos de teste não foram usados nos treinos
anteriores. Essa confirmação não identifica pessoas automaticamente: confira a origem dos dados.
O histórico de modelos treinados pelo 3.0 é verificado para impedir que seu treino apareça no teste.

O objetivo **Classificador de cabeças** exporta recortes `com_capacete`/`sem_capacete` em
divisões independentes. Recortes inconclusivos ficam fora desse dataset. O treino desse classificador
separado **não está habilitado** nesta entrega: falta definir e validar um modelo inicial próprio.
O botão de treinamento atual aceita o **detector EPI compatível**, mantendo cinco classes.

Em **Iniciar Treinamento da IA**, escolha modelo inicial, dataset, épocas (1–300), resolução,
batch (1–4), CPU/CUDA e nome. O treino completo exige no mínimo 100/30/30 imagens e exemplos
das cinco classes. O piloto exige escolha explícita, no mínimo 8/2/2, e não comprova precisão
nem preservação das outras classes. Nada começa automaticamente após importar ou revisar.

Treino, sugestões, importação e preparação rodam em processos separados, com logs e progresso.
Só um trabalho pesado fica ativo de cada vez. Treino/sugestões/avaliação exigem monitoramento
encerrado. O cancelamento é cooperativo; após 30 segundos sem encerramento, somente o processo
filho daquele trabalho pode ser terminado. Checkpoints já gravados e todos os pesos anteriores
permanecem preservados. Interrupção forçada pode impedir um checkpoint da época corrente.

Resultados novos ficam em `modelos/<id-do-trabalho>`, incluindo `best.pt` e `last.pt` quando
o treinador os gerar. Nenhum peso original é substituído ou promovido automaticamente.
**Comparar com original** avalia no teste independente. Aprovação exige classes compatíveis,
cobertura das cinco classes no teste e ausência de regressão nos critérios implementados,
além de confirmação explícita. A avaliação por imagens não substitui a revisão de vídeos e alertas.
É possível selecionar um modelo aprovado com o monitoramento parado e retornar ao original.

## Mais de 10 pessoas e apenas um capacete

O 3.0 mantém uma inferência global de pessoas e uma global de capacetes. Não há corte em
quatro/cinco pessoas: todas as detecções entram no rastreamento e no painel.
Um capacete é associado a no máximo uma pessoa; associações próximas/ambíguas ficam inconclusivas.

A reanálise de cabeças usa uma fila por identidade temporária estimada, atendendo primeiro
quem está esperando há mais tempo. A espera não conta como observação negativa. O histórico
de observações reais de ausência possível pode atravessar espera curta, mas nunca é incrementado
ou confirmado em quadro pendente e expira após dois segundos sem observação válida.

Uma referência de rosto global/pose atual verifica detalhe, iluminação, bordas e ambiguidade
da cabeça. Isso permite avaliar uma cabeça visível mesmo quando os pés/corpo estão cortados.
Cabeças pequenas, ocultas ou mal associadas continuam inconclusivas. Não se baixaram limiares
de confirmação nem se afirmou uma classe `no_helmet` que os pesos não possuem.

Por padrão, o orçamento é **8 poses e 4 reanálises de cabeça por rodada**, com fila justa;
isso é um orçamento de detalhes, não um limite de pessoas. Pessoas sem pose atual não recebem
uma postura antiga como se fosse nova: a análise temporal fica inconclusiva/interrompida para
não interpretar atraso como imobilidade. Em sobrecarga, a sensibilidade de quedas pode diminuir.
Essa limitação aparece no painel e precisa ser medida na T400.

Para analisar todas as poses em cada quadro, com maior custo de CPU:

```powershell
$env:VIGIAAI_POSES_POR_QUADRO='0'
$env:VIGIAAI_CABECAS_POR_QUADRO='8'
.\.venv3\Scripts\python.exe iniciar3.py --port 5013
```

O painel coletivo mostra contagens reais do quadro: pessoas, capacete detectado, possível
ausência, inconclusivas/observando, possíveis quedas e FPS. A fila e o motivo individual da
cabeça aparecem separadamente. Uma leitura pendente não é contada como ausência confirmada.
O botão **Modo Apresentação — Capacete e Postura** e o retorno à política normal são preservados.

## Persistência e backup

Padrão: **Documentos/VigiaAI-Dados**, usando a pasta Documentos conhecida pelo Windows
(inclusive quando redirecionada). Pode ser alterado por `VIGIAAI_DATA_DIR` ou `--data`.

| Pasta | Conteúdo |
|---|---|
| `imagens/originais` | Bytes originais imutáveis, nomes/origens no catálogo |
| `imagens/miniaturas`, `imagens/visualizacao` | Derivados para a interface, sem alterar os originais |
| `anotacoes` | Revisões, anotações importadas e metadados |
| `datasets` | Snapshots auditados e congelados |
| `modelos` | Novos experimentos e checkpoints |
| `trabalhos` | Pedidos, progresso e logs dos processos |
| `relatorios` | Relatórios locais |
| `backups` | Snapshots consistentes do catálogo SQLite |
| `importacoes` | Uploads completos/incompletos preservados |

Pendentes/revisadas/aprovadas/rejeitadas são estados do catálogo, evitando mover ou duplicar
originais entre pastas. Uma versão nova extraída em outra pasta encontra o mesmo banco de dados.
Não mude a raiz de dados entre versões sem copiar todo o conteúdo de forma verificada.

**Criar backup do catálogo** não substitui backup de fotos/pesos. Para backup completo,
encerre somente o VigiaAI 3.0 e copie toda a pasta `VigiaAI-Dados` para uma pasta nova em
outro disco. Preserve o original e confirme a cópia antes de usar. O original da apresentação
não precisa ser parado ou alterado por esse procedimento.

## Validação, vídeos e limites

Consulte [RELATORIO-3.0.md](RELATORIO-3.0.md). Não há vídeos reais de grupos ou acesso à
T400/webcam da apresentação nesta sessão; nenhum ganho de FPS ou precisão industrial é declarado.
O navegador automatizado não alcançou o servidor local, portanto a interface foi validada por
JavaScript real conectado às rotas Flask, com DOM simulado, além dos testes de backend.

Para um vídeo autorizado com 20 pessoas, primeiro a base, depois o 3.0:

```powershell
.\.venv3\Scripts\python.exe benchmark_grupos.py --video 'C:\Videos\grupo20.mp4' --people-declared 20 --output 'C:\Medicoes\antes20' --device 0 --baseline
.\.venv3\Scripts\python.exe benchmark_grupos.py --video 'C:\Videos\grupo20.mp4' --people-declared 20 --output 'C:\Medicoes\depois20' --device 0
```

Repita com 1, 5, 10, 15, 20 e, quando houver vídeo adequado, 25 pessoas. Faça três execuções
sequenciais por caso, com mesma política, driver e vídeo, sem concorrência na GPU/webcam.
Os relatórios separam processamento, latência, recursos e contagens observadas. Número declarado
não é ground truth. Trocas de identidade, capacetes associados errado, falsos alertas e alertas
perdidos exigem anotações independentes. Não use FPS sozinho para aprovar uma mudança.

### Executar os testes

```powershell
.\.venv3\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
$env:VIGIAAI_PYTHON=(Resolve-Path '.\.venv3\Scripts\python.exe').Path
node --test tests/test_web.mjs
```

Os testes precisam da base integrada. Node.js é necessário apenas para o teste JavaScript.
O teste manual `tests/smoke_training.py` executa uma época real CPU em dados sintéticos
explicitamente identificados, exclusivamente para validar a engenharia. Não comprova reconhecimento
de capacetes e não promove o modelo. Ele não roda automaticamente nos testes comuns.

Fontes técnicas: [callbacks Ultralytics](https://docs.ultralytics.com/usage/callbacks/),
[treinamento](https://docs.ultralytics.com/modes/train/),
[validação](https://docs.ultralytics.com/modes/val/).
