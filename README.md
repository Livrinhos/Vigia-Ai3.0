# VigiaAI — Performance e 3.0 no mesmo projeto

Este repositório contém o **código completo das duas versões**, com **uma instalação única**.
Não é necessário selecionar pasta, importar outro ZIP nem obter uma extensão separada.

| Versão | Conteúdo | Iniciador | Endereço |
|---|---|---|---|
| VigiaAI Performance | Monitoramento otimizado e Modo Apresentação — Capacete e Postura | Iniciar-Performance.cmd | http://127.0.0.1:5011 |
| VigiaAI 3.0 | Monitoramento coletivo, Banco de Imagens, anotação, datasets e treinamento | Iniciar-VigiaAI3.cmd | http://127.0.0.1:5013/banco |

## Instalar em um Windows novo

1. Instale [Python 3.12 x64](https://www.python.org/downloads/release/python-31210/) com Python Launcher.
2. Baixe **esta branch** em **Code → Download ZIP** e use **Extrair tudo** em uma pasta nova.
3. Abra a pasta extraída e execute **Instalar.cmd**. Aguarde a conclusão.
4. Abra **Iniciar-Performance.cmd** ou **Iniciar-VigiaAI3.cmd**. Também pode usar **Escolher-Versao.cmd**.

O instalador prepara as duas versões no ambiente separado `.venv3`, identifica NVIDIA quando
possível e instala CUDA ou CPU. Ele baixa automaticamente os três pesos originais que faltarem,
verifica tamanho/SHA-256 e não substitui pesos existentes. A primeira instalação requer internet
para dependências e modelos. Não aparece mais a janela de seleção de ZIP que causava o erro anterior.

Para escolher CPU explicitamente, execute no PowerShell desta pasta:

```powershell
.\Instalar.cmd -Dispositivo cpu
```

Para NVIDIA explicitamente: `.\Instalar.cmd -Dispositivo cuda`.
O instalador informa se o PyTorch realmente reconheceu CUDA; um driver incompatível não é tratado
como GPU funcionando. Não atualiza drivers automaticamente.

Mantenha a janela do iniciador aberta. Execute **uma versão por vez** para não disputar webcam/GPU.
A porta 5001 do sistema original não é usada por estes iniciadores. A instalação original da apresentação
não é modificada. Não extraia esta atualização sobre ela.

## Onde estão as duas versões

- `performance/`: código completo Performance — Flask, YOLO, MediaPipe, EPIs, quedas, interface e testes.
- `vigia3/` e `web/`: recursos 3.0 e Banco de Imagens, usando a mesma base preservada.
- `preparar_instalacao.py`: verificação e obtenção automática dos pesos, sem outro pacote.
- `Instalar.cmd`: instalação única; os dois iniciadores usam o mesmo ambiente.

Os pesos conhecidos são obtidos do commit de origem verificado; arquivos de treinamento particulares
não são publicados. Se um arquivo existente tiver hash diferente, o instalador o preserva e interrompe
com orientação em vez de sobrescrevê-lo. O arquivo `integrar_base.py` permanece só por compatibilidade
com comandos antigos; ele também não exige mais ZIP.

## Fotos, treinamento e persistência

As fotos, anotações, datasets, modelos novos e relatórios continuam em **Documentos/VigiaAI-Dados**,
separados do código. Baixar outra versão por ZIP não apaga esses dados.

Para importar as fotos antigas, abra **VigiaAI 3.0 → Banco de Imagens e Treinamento** e selecione
imagens, ZIP ou a pasta `amostras_epi/pendentes`. Nenhuma imagem é aprovada ou usada em treino
automaticamente. Revisão humana, auditoria e aprovação de modelos continuam obrigatórias.

Para agilizar as marcações, filtre a galeria, use **Selecionar todas do filtro** e
**Sugerir marcações em lote**. Depois abra **Revisar selecionadas** e **Salvar e próxima**.
As caixas são sugestões: revisão humana por imagem continua obrigatória e nada é treinado
automaticamente. Anotações existentes e pesos originais são preservados.

Leia o [guia do Banco de Imagens](GUIA-BANCO.md) e o [relatório de implementação](RELATORIO-3.0.md).
O treino de um classificador separado de cabeças não está habilitado: existe o esquema e a exportação.
O treinamento disponível é do detector EPI compatível, sem inventar objetos `no_helmet`.

## Preservação e limites

Os três pesos originais mantêm seus hashes. Nenhum treinamento é executado pelo instalador.
Modelos novos são gravados separadamente e não são promovidos automaticamente.
O código do Samuel conserva os créditos e o commit de origem; veja [origem e permissões](ORIGEM-E-PERMISSOES.md).
O repositório original e a `main` deste repositório não recebem alterações desta branch.

Não há ganho de FPS confirmado na T400. Cenas reais de 10–20+ pessoas ainda exigem medição e revisão.
Pessoas sem detalhes atuais suficientes são mostradas como pendentes/inconclusivas, sem alertas inventados.

## Testes

```powershell
.\.venv3\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
.\.venv3\Scripts\python.exe -m unittest discover -s performance/tests -p 'test_*.py'
$env:VIGIAAI_PYTHON=(Resolve-Path '.\.venv3\Scripts\python.exe').Path
node --test tests/test_web.mjs
node --test performance/tests/test_*.mjs
```

Node.js é necessário somente para os testes JavaScript. Os smoke tests de treinamento são manuais
com dados sintéticos explícitos e não comprovam precisão industrial.
