# VigiaAI 3.0 — relatório de implementação e validação

Data: 13/11/2026. Base preservada: VigiaAI-Performance, construída a partir de
`susuque-samuel/VigiaAi@e1d054ef33ea1fd007d31ed9c96440327f81859f`.

## Entrega

O desenvolvimento continua na branch `development/vigiaai-3-banco-imagens` do repositório
`Livrinhos/Vigia-Ai3.0`. A `main` não é usada para publicar estas mudanças e não há merge automático.
O repositório do Samuel não foi modificado.

O repositório público recebe somente módulos novos, interface, integrador, testes e documentação.
A base anterior e seus três pesos são integrados localmente, a partir do ZIP privado autorizado,
com validação do hash do arquivo completo e dos pesos. O pacote local completo entregue ao usuário
já pode conter essa base integrada. Isso evita republicar o código original sem autorização pública
esclarecida: ele continua sem LICENSE declarada, e a autorização anterior se referia à cópia privada.
Nenhum dado ou credencial é necessário no GitHub para executar a aplicação local.

## Funcionalidades reais implementadas

| Área | Implementação |
|---|---|
| Upload individual e múltiplo | Blocos de até 4 MB, validação do offset, armazenamento temporário e trabalho separado para importar |
| Pasta local | Seleção `webkitdirectory`, preservando caminhos relativos e associando TXT/JSON por nome |
| ZIP | Preflight de todas as entradas, limites de quantidade/tamanho/expansão, sem `extractall`, rejeição de fuga, links, executáveis, criptografia e arquivos aninhados |
| Imagem | Pillow decodifica o conteúdo real; JPG/PNG/WebP estáticos, limite de pixels e alertas de qualidade |
| Persistência | Documentos conhecido pelo Windows + `VigiaAI-Dados`, separado do código e de novos Downloads ZIP |
| Galeria | Pesquisa, sessões, filtros, paginação, seleção múltipla, lixeira recuperável e contagens consultadas do banco |
| Originais | Bytes imutáveis, SHA-256 e hash de pixels, nomes/origens no catálogo, derivados separados para visualização |
| Metadados | JSON de origem e anotações importadas preservados sem tratá-los como verdade automaticamente |
| Duplicatas | Reconhecimento por bytes/pixels, registro de todas as origens e anotações alternativas; dHash para reunir imagens semelhantes |
| Anotação | Canvas para desenhar, selecionar, alterar rótulos e remover/redesenhar caixas; revisão humana e controle de versão concorrente |
| Sugestões IA | Worker com o peso existente; sugestões não alteram o estado de revisão e precisam de aprovação humana |
| Dataset | Apenas imagens aprovadas, união de grupos/semelhantes antes da divisão, YAML e manifesto, auditoria da base e selo de integridade |
| Treinamento | Processo separado, parâmetros limitados, CPU/CUDA verificada, logs, progresso, cancelamento e checkpoints em diretório novo |
| Modelos | Registro por hash, comparação original/candidato no teste, cobertura de classes e aprovação explícita; seleção apenas com monitoramento parado |
| Retorno | Seleção do original preservado; configurações da demonstração não substituem os pesos |
| Coletivo | Todas as detecções entram no rastreamento; associação individual de capacete, fila justa de cabeças e orçamento de poses transparente |

Classes EPI **0 capacete, 1 colete, 2 oculos, 3 luvas, 4 mascara** permanecem compatíveis.
Regiões auxiliares de pessoa/cabeça não mudam essa lista. `sem_capacete` é rótulo de um recorte
de cabeça para classificador separado, não uma caixa falsa de objeto `no_helmet`.

## Por que havia tantos resultados laranja

Foram identificadas limitações reais do fluxo anterior:

1. A reanálise local era limitada a quatro candidatos por rodada, com rotação por posição na
   lista. O custo cresce com várias pessoas e a ordem pode mudar entre quadros.
2. Uma pessoa esperando reanálise podia perder suas observações anteriores, porque pendência
   era tratada como sinal negativo na rotina que limpa confirmações. Isso pode impedir que uma
   sequência de observações suficientes se forme mesmo em uma cena estável.
3. O teste de visibilidade de capacete dependia de pontos da pose e de condições do corpo inteiro,
   como pés/corpo dentro da imagem. Uma cabeça suficientemente visível podia continuar bloqueada
   por causa de outra parte do corpo cortada.
4. Em grupos distantes, cabeça/olhos pequenos realmente não oferecem informação suficiente.
   Nenhuma alteração de software recupera detalhes que a câmera não capturou.
5. Os pesos não possuem classe de ausência de capacete e têm limitações de reconhecimento.
   Não detectar capacete não comprova que ele está ausente.

O 3.0 introduz uma fila pelo atendimento mais antigo, usando a identidade temporária anterior
quando a associação é suficientemente clara. Espera curta preserva **somente** observações
anteriores válidas: não incrementa contagem, não confirma e não dispara alerta. A evidência expira
depois de dois segundos sem observação válida e é interrompida por ambiguidades.

A referência de cabeça utiliza rosto global/pose **atual**, detalhe em pixels, iluminação,
contraste, enquadramento e ambiguidade. Reanalisa a região de cabeça, reduzindo contexto inútil
e ampliando esse detalhe para o detector. Isso pode ajudar o reconhecimento, mas ainda exige
validação com vídeos reais. Não houve redução silenciosa de limiares temporais.

Capacete positivo não passa a depender de rosto visível: uma detecção forte de capacete pode
continuar presente mesmo quando o rosto não fornece evidência suficiente para avaliar ausência.
O requisito de cabeça verificável se aplica à **possível ausência**, que continua sujeita a
confirmação, política escolhida e verificação humana. Nenhuma infração confirmada é inventada.

## Grupos, poses e quedas

Há uma inferência global de pessoas e uma global de EPIs, reaproveitando o pipeline Performance.
Não foi introduzido limite de quatro/cinco pessoas no rastreamento. O YOLO mantém seu limite
geral de detecções, que é superior ao cenário de 20–25 pessoas aqui testado logicamente.

O orçamento padrão é oito poses e quatro reanálises de cabeça por quadro. A fila atende todas
as pessoas ao longo das rodadas. `VIGIAAI_POSES_POR_QUADRO=0` permite todas as poses por quadro,
com custo maior. O limite de reanálises é configurável por `VIGIAAI_CABECAS_POR_QUADRO`.

Uma pose não calculada não é substituída por marcos antigos. Ela aparece pendente/inconclusiva,
e o motor original não recebe uma falsa observação de imobilidade. Isso reduz risco de falsas
quedas por atrasos, mas pode reduzir a sensibilidade de quedas em sobrecarga. O painel informa
essa condição. A solução não garante quedas confiáveis com 20 pessoas na T400 sem medição real.

IDs são temporários, sem reconhecimento biométrico/ReID. Cruzamentos/oclusões podem produzir
ambiguidades ou novos IDs; confirmações não são mantidas como se a identidade fosse certa.
O sistema não promete eliminar trocas de identidade. Elas precisam de vídeos anotados para medir.

As contagens coletivas usam os estados atuais reais: capacete presente, possível ausência e
inconclusivo/observando. Pessoas em fila não são somadas como ausência confirmada. Motivos
individuais de cabeça e quantidade de poses/reanálises pendentes ficam visíveis.

## Dataset e independência

As divisões são por componentes de origem, não por imagens avulsas. Mesma sessão/grupo,
duplicatas e imagens muito semelhantes ficam juntas. Reimportar uma duplicata em outra sessão
preserva a ligação entre as origens, evitando que ela esconda uma possível conexão entre divisões.

O agrupamento depende dos nomes de origem/pessoas informados pelo usuário. Não há identificação
automática de pessoas, e dHash não detecta toda semelhança possível. Imagens da mesma gravação
ou pessoa importadas em sessões diferentes devem receber o mesmo grupo.

Dataset preparado é snapshot imutável, com originais copiados, labels revisados, YAML, manifesto
e hashes. Revisão, lixeira ou origens que mudem depois invalidam o uso desse snapshot para novo
treino/avaliação; o snapshot anterior não é apagado. O worker confere a integridade novamente.

A comparação exige declaração explícita de que o teste não foi usado em treinos anteriores.
O histórico do 3.0 registra as imagens/grupos de treino e bloqueia sobreposição conhecida com
o teste. O histórico de pré-treinamento dos pesos originais não está integralmente disponível:
essa independência não é anunciada como comprovada automaticamente.

O treino completo exige exemplos das cinco classes e 100/30/30 imagens. O modo piloto permite
8/2/2 por escolha explícita. Um piloto focado somente em capacetes não comprova preservação
das outras classes e não passa automaticamente pela promoção. A avaliação de promoção exige
cobertura das cinco classes e critérios sem regressão por classe, além da confirmação humana.

## Validações executadas

| Teste | Evidência |
|---|---|
| Base preservada | 167 testes Python e 7 JavaScript anteriores aprovados novamente |
| Módulos 3.0 | 23 testes Python, incluindo importação/galeria/revisão/dataset, fila coletiva, processos e bloqueio da segunda instância |
| JavaScript 3.0 | Script real da página conectado a rotas Flask reais via ponte, com DOM simulado; importação, abrir imagem e salvar aprovação |
| Importação em escala | ZIP com 200 PNGs distintos, TXT YOLO e JSON; nenhum aprovado automaticamente |
| Arquivos maliciosos | Fuga de caminho, link simbólico, ZIP aninhado, expansão excessiva, formato inválido e classes incompatíveis rejeitados |
| Grupos simulados | 1, 5, 10, 15, 20 e 25 pessoas; apenas um capacete associado a uma pessoa |
| Ausência possível | Cena simulada de 20 pessoas; as 19 sem detecção de capacete recebem atendimento e podem formar observações válidas, sem contar espera como evidência |
| Cruzamento/ambiguidade | Associação ambígua fica inconclusiva; cabeças sem detalhe não geram certeza |
| Dataset | Auditoria real da base, independência de grupos, exclusão de pendentes, integridade e invalidação após nova revisão |
| Processos | Exclusão mútua e cancelamento cooperativo, além de rejeição de IDs de processos não pertencentes ao gerenciador |
| Carga real do detector | PyTorch 2.6.0 CPU e Ultralytics 8.4.144 carregaram `epi.pt`; inferência em imagem sintética concluída |
| Treino real | Uma época CPU, resolução 320, batch 1, dataset sintético com 36 imagens/6 grupos, sem promoção |
| Sugestão real | Worker do detector executado; não alterou anotações nem revisão da imagem |
| Comparação real | Candidato e original avaliados no teste sintético; candidato não promovido |
| Cancelamento real | Outro treino CPU cancelado após começar; `best.pt`, `last.pt` e checkpoints já escritos permaneceram disponíveis |
| Preservação | Hashes dos três pesos originais iguais após inferência, treino, comparação e cancelamento |
| Interface visual no navegador | Não concluída: o navegador automatizado não alcançou o servidor local. Backend e JS foram testados pela ponte; não se afirma verificação visual completa |
| T400/webcam/vídeos reais | Indisponíveis nesta sessão; sem resultados inventados |

Os dados sintéticos de engenharia não são pessoas reais nem comprovação de reconhecimento.
O candidato sintético não foi selecionado no monitoramento e não é entregue como modelo recomendado.
Os testes comuns não executam treinamento; os smoke tests reais exigem comando manual explícito.

### Preservação dos pesos da base

| Peso | SHA-256 |
|---|---|
| `yolov8n.pt` | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` |
| `epi.pt` | `1f9fdde980c2e56c22c8857b778b5213fb07fc21fbcdb05fe71ef9c1fb50ce0e` |
| `runs/detect/treinamento_epi-2/weights/best.pt` | `eeac8b62d3d78052c736981dd7ad1554a8902ff179b5543d1706f35c9d221bf5` |

Não houve acesso às fotos, datasets, pesos extras ou checkpoints exclusivos do computador da
apresentação. A ferramenta está pronta para importá-los posteriormente pelo navegador; não se
afirma que esses arquivos já foram copiados, inventariados ou protegidos por esta sessão.

## Limites e próximos testes no PC da apresentação

- FPS, latência e consumo da T400 com 1/5/10/15/20+ pessoas ainda não foram medidos.
- Não há garantia de 10 FPS. A medida aproximada de 5 FPS permanece apenas o relato anterior.
- Precisão de capacetes/ausência, troca de IDs e falsos alertas exigem vídeos anotados independentes.
- O classificador dedicado de cabeça possui esquema e exportação de dados; seu treino/inferência
  não estão habilitados nesta versão. O detector atual continua sem classe negativa inventada.
- A distribuição por sessão reduz vazamento, mas depende de informação correta sobre pessoas/gravações.
- A confirmação de ausência pode permanecer inconclusiva quando os detalhes ou a cadência são insuficientes.
- Só um servidor 3.0 pode utilizar uma mesma pasta de dados por vez. Reinícios reconhecem workers
  ainda vivos para evitar disputa de GPU; cancelamento recuperado é cooperativo, sem matar processos de terceiros.
- O backup do catálogo SQLite não substitui uma cópia externa completa da pasta de dados.

O procedimento de instalação, importação das pastas antigas e benchmark real está no README.
Nenhum resultado fictício foi usado para tornar a apresentação mais impressionante.
