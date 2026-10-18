# psa_obd — Diagnóstico OBD2 PSA via Wi-Fi (Citroën C4 Cactus 2022 1.6)

Aplicação em **Python puro** (somente biblioteca padrão, sem `pip install`) com painel web local, para adaptadores **ELM327 Wi-Fi** (testado com o "PSA by Costa Car") em carros Peugeot/Citroën.

O que ela faz:

- mostra dados **ao vivo** do motor (RPM, velocidade, temperaturas, lambdas, ajustes de combustível etc.);
- lê e apaga **falhas (DTC)** da central do motor e consulta as descrições na **tabela de falhas Peugeot/Citroën** (2.632 códigos, 54 famílias de módulos);
- mostra VIN, protocolo e PIDs suportados;
- faz **reset da central do motor** (UDS `11`), com travas de segurança;
- faz um **diagnóstico de capacidades** das centrais (somente leitura), para planejar novas funções;
- consulta **outros módulos** (ABS, airbag, painel, BSI...) com serviços UDS/KWP **somente leitura**, interpretando as falhas lidas;
- registra **todos os comandos e respostas** em um log que pode ser baixado;
- grava **em arquivo, para sempre**, cada conexão com a central com data e hora (`logs/conexoes.log`, veja a [seção 18](#18-log-permanente-de-conexões));
- mostra a **versão** do app e o histórico de versões ([CHANGELOG.md](CHANGELOG.md), [seção 19](#19-versionamento-e-publicação)).

Funciona em Windows, Linux e macOS (Python 3.8 ou superior).

> **Aviso:** projeto pessoal e experimental, sem garantia. Mexer na comunicação de um carro envolve risco. Use com o carro parado, entenda cada função antes de usar e **nunca** opere o painel com o veículo em movimento. Apagar falhas e resetar a central são ações reais no carro.

---

## Sumário

1. [Status de validação](#1-status-de-validação)
2. [Requisitos](#2-requisitos)
3. [Estrutura do projeto](#3-estrutura-do-projeto)
4. [Uso no carro (passo a passo)](#4-uso-no-carro-passo-a-passo)
5. [Abas do painel](#5-abas-do-painel)
6. [Lendo as falhas de ABS, airbag e painel](#6-lendo-as-falhas-de-abs-airbag-e-painel)
7. [O que o app não faz (segurança)](#7-o-que-o-app-não-faz-segurança)
8. [Testar sem o carro (simulador)](#8-testar-sem-o-carro-simulador)
9. [Solução de problemas](#9-solução-de-problemas)
10. [Como o app funciona por dentro](#10-como-o-app-funciona-por-dentro)
11. [API HTTP local](#11-api-http-local)
12. [Tabela de falhas Peugeot](#12-tabela-de-falhas-peugeot)
13. [Limites conhecidos](#13-limites-conhecidos)
14. [Como ajudar a validar no seu carro](#14-como-ajudar-a-validar-no-seu-carro)
15. [Desenvolvimento e publicação no GitHub](#15-desenvolvimento-e-publicação-no-github)
16. [Dados de terceiros e créditos](#16-dados-de-terceiros-e-créditos)
17. [Glossário](#17-glossário)
18. [Log permanente de conexões](#18-log-permanente-de-conexões)
19. [Versionamento e publicação](#19-versionamento-e-publicação)
20. [Licença](#20-licença)

---

## 1. Status de validação

| Função | Situação |
|---|---|
| Conexão Wi-Fi/TCP, protocolo CAN 11 bit 500 kbps (ELM `6`) | Validado no carro |
| Dados ao vivo (modo 01), falhas OBD (03/07/0A), Info (VIN, protocolo) | Validado no carro |
| Log de comandos e respostas | Validado no carro |
| Aba Capacidades (varredura somente leitura) | Validado no carro em 17/10/2026 |
| Reset da ECU, aba Módulos, falhas de módulos (UDS/KWP), consulta à tabela Peugeot | Testado **só no simulador** |
| Log permanente de conexões, versionamento | Testado no simulador (v1.1.0) |

Resultado do teste real (Cactus 2022 1.6): protocolo ISO 15765-4 CAN 11 bit/500 kbps; luz de injeção apagada e nenhuma falha armazenada; a central do motor responde (`7E8`) aos PIDs 01, 03, 04, 05, 06, 07, 0B, 0C, 0D, 0E, 0F, 11, 13, 14, 15, 1C, 21, 2E, 30, 33, 42, 47, 49, 4A, 4D, 51 e 52; **não** informa vazão de ar (MAF), nível de combustível nem temperatura do óleo pela porta OBD; uma segunda central (`7E9`) responde pouca coisa.

O que está "só no simulador" pode se comportar diferente no carro real. Confira sempre o dado bruto na aba **Log**.

## 2. Requisitos

- Python 3.8+ (`python --version`). Nada para instalar com `pip`.
- Adaptador ELM327 Wi-Fi plugado na porta OBD2 do carro.
- Computador com Wi-Fi e navegador.

> **Windows:** use `python`. O `python3` do Windows é só um atalho da Microsoft Store e não funciona.
> **Linux/macOS:** use `python3`.

## 3. Estrutura do projeto

```
psa_obd/
├── app.py               servidor local + API do painel
├── elm327.py            cliente TCP do ELM327, PIDs, falhas, VIN, log, reset da ECU
├── pids.py              fórmulas dos PIDs, monitores, descrições de falhas, consulta à tabela Peugeot
├── capabilities.py      diagnóstico de capacidades (varredura somente leitura)
├── audit.py             log permanente de conexões (logs/conexoes.log)
├── version.py           número da versão (SemVer)
├── CHANGELOG.md         histórico de versões
├── modules.py           consultas UDS/KWP somente leitura e leitura de falhas de módulos
├── simulator.py         adaptador ELM327 falso para testar sem o carro
├── dtc_peugeot.json     tabela de falhas Peugeot/Citroën (opcional, arquivo local; não vem no repositório)
├── LICENSE              licença (uso não comercial)
├── tools/
│   └── release.py       publica uma versão (version.py + changelog + commit + etiqueta)
└── web/
    └── index.html       painel (uma página, sem frameworks)
```

| Arquivo | Função |
|---|---|
| `app.py` | Sobe o servidor HTTP em `127.0.0.1`, gerencia a conexão, a leitura ao vivo em segundo plano e o diagnóstico de capacidades |
| `elm327.py` | Comandos AT, protocolo, tentativas e *timeouts*, junção de respostas de várias centrais e de quadros multi-frame (ISO-TP), VIN, leitura/limpeza de falhas, reset da ECU e o buffer de log (últimas 5.000 linhas) |
| `pids.py` | Decodificação dos PIDs do modo 01, status de prontidão (MIL e monitores), descrição de falhas em português (~90 códigos genéricos) e consulta à tabela Peugeot |
| `capabilities.py` | Remontagem de respostas ISO-TP com cabeçalhos e varredura de cada central (modos 01/02/06/09, falhas, leituras UDS) |
| `modules.py` | Lista de serviços liberados e bloqueados, envio de consultas a um par de IDs CAN e interpretação de falhas UDS (`19 02`) e KWP (`17`/`18`) |
| `simulator.py` | Simula um ELM327 com duas centrais, módulos fictícios e opções de falha |

## 4. Uso no carro (passo a passo)

1. Plugue o adaptador na porta OBD2 (sob o painel, lado do motorista).
2. Ligue a ignição (ou o motor). Para o reset da ECU e para ler módulos como ABS e airbag, **deixe o motor desligado e a ignição ligada**.
3. Conecte o computador ao **Wi-Fi do adaptador** (nome como `WiFi_OBDII`, `OBDII`, `V-LINK` ou parecido; senha comum `12345678`, ou sem senha; veja o manual). O computador fica **sem internet** enquanto estiver nessa rede.
4. Na pasta do projeto, rode:
   ```
   python app.py
   ```
5. Abra http://localhost:8080 no navegador e clique em **Conectar**.

O padrão da maioria dos ELM327 Wi-Fi é IP `192.168.0.10`, porta `35000`. Se o seu for diferente, altere os campos no topo do painel ou use:

```
python app.py --host 192.168.x.x --port NNNN
```

| Opção | Padrão | Significado |
|---|---|---|
| `--host` | `192.168.0.10` | IP do adaptador Wi-Fi |
| `--port` | `35000` | Porta TCP do adaptador |
| `--web-port` | `8080` | Porta do painel no seu computador |

O painel escuta apenas em `127.0.0.1` (não fica exposto na rede).

**Para descobrir o IP do adaptador:** com o Wi-Fi do adaptador conectado, o IP do gateway é o do adaptador. Windows: `ipconfig` (campo "Gateway Padrão"). Linux: `ip route | grep default`.

**Linux, conectar ao Wi-Fi pelo terminal:** `nmcli device wifi connect "NOME_DA_REDE" password "SENHA"`

## 5. Abas do painel

### Painel
Dois layouts, com seletor **Digital / Clássico** no topo (a escolha fica salva no navegador):

- **Digital** (padrão): estilo painel moderno, com velocímetro e conta-giros em arco com marcador, números grandes, barra de temperatura do motor (C–H) sob o velocímetro, segmentos de combustível (E–F) sob o conta-giros, luzes de aviso no topo, relógio, temperatura do ar de admissão, **gráfico ao vivo** de rotação e velocidade (últimos ~30 s) e uma faixa inferior com **trajeto, velocidade média, velocidade máxima e tempo**, calculados pelo app a partir da velocidade lida (botão Zerar).
- **Clássico**: mostradores redondos com ponteiro e luzes de aviso, descrito a seguir.

**Tela cheia:** botão no topo do painel ou tecla **F** (Esc sai). Os instrumentos crescem para ocupar a tela inteira, os botões somem sozinhos após 3 s sem mexer o mouse (e voltam ao mexê-lo) e, onde o navegador permite, a tela não apaga enquanto o painel está em tela cheia. Funciona nos dois layouts.

Não aparecem itens que a central do motor não informa (marcha, navegação, assistente de faixa, autonomia, odômetro), para o painel mostrar só dado real.

Painel de instrumentos animado, como o de um carro: **conta-giros**, **velocímetro**, **temperatura do motor** e **combustível**, com ponteiros que se movem suavemente e um arco que acende conforme o valor. Zona vermelha no conta-giros (acima de 6.000 rpm), temperatura fria/quente colorida e luzes de aviso:

| Luz | Acende quando |
|---|---|
| Adaptador | conectado ao adaptador |
| Motor ligado | rotação acima de 400 rpm |
| Injeção | a luz de injeção (MIL) do carro está acesa (status lido a cada poucos segundos) |
| Falhas | há códigos de falha confirmados |
| Carga | tensão da ECU abaixo de 13 V (alerta) ou 12 V (crítico) com o motor ligado, ou acima de 15,2 V |
| Temp. motor | acima de 105 °C (alerta) / 112 °C (crítico), ou azul abaixo de 50 °C (motor frio) |
| Combustível | abaixo de 15 % (só se o carro informar) |

Abaixo dos mostradores há cartões com tensão, carga, borboleta, pedal, ar de admissão, pressão do coletor, avanço e etanol.

- **O Cactus não informa o nível de combustível pela porta OBD**, então o mostrador de combustível fica em `N/D` neste carro (aparece normalmente em carros que informam o PID 2F).
- **Modo demonstração:** simula valores para ver o painel funcionando sem o carro (aparece a etiqueta DEMONSTRAÇÃO). Também abre direto em http://localhost:8080/#demo (e `/#classic-demo` para o layout clássico).
- **Animação de teste:** ponteiros vão ao fim da escala e voltam e as luzes acendem, como ao ligar um carro. É **só uma animação na tela**: não envia nenhum comando ao carro e não testa o painel de instrumentos do veículo. Roda sozinha ao abrir a página.
- **Leitura rápida** (botão no topo, ligada por padrão): nas leituras ao vivo o app acrescenta o sufixo de contagem do ELM327 (por exemplo `010C1`), e o adaptador devolve assim que a 1ª central responde, em vez de esperar o tempo limite de ~200 ms. No log do seu carro cada leitura levava ~205 ms (ou ~409 ms com duas centrais), tempo que era quase todo espera. A taxa medida aparece no rodapé do painel ("N leituras/s"). Se o adaptador não aceitar o sufixo, o app volta sozinho ao modo normal. O status (luz de injeção) continua sendo lido pelo modo normal.
- **Luz de carga:** só avalia a tensão 12 s depois de o motor pegar, porque no arranque a tensão cai (motor de partida) antes de o alternador carregar. Rotação, velocidade, temperatura do motor e tensão são lidas a cada ciclo.
- Valores com mais de 30 s sem atualização somem (`--`). Os ponteiros usam animação CSS e respeitam a opção "reduzir movimento" do sistema.

### Ao vivo
Cartões com mini-gráfico do histórico recente (últimas 60 leituras). RPM, velocidade, temperatura da água e do ar, carga, borboleta, MAP, avanço, ajustes de combustível (curto e longo), lambdas, tensão da ECU, etanol no combustível, purga do EVAP e outros. **Só aparecem os PIDs que a central declara suportar.** RPM e velocidade são lidos a cada ciclo; os demais entram em rodízio (um por ciclo), para manter a leitura rápida.

PIDs decodificados (modo 01): 03 estado do sistema de combustível · 04 carga do motor · 05 temp. água · 06/07 ajuste de combustível curto/longo B1 · 0A pressão de combustível · 0B MAP · 0C RPM · 0D velocidade · 0E avanço · 0F temp. ar admissão · 10 MAF · 11 borboleta · 14/15 lambdas B1S1/B1S2 · 1F tempo desde a partida · 1C norma OBD · 21 distância com MIL · 2E purga EVAP · 2F nível de combustível · 30 partidas desde apagar falhas · 33 pressão barométrica · 42 tensão da ECU · 43 carga absoluta · 44 lambda comandada · 45 borboleta relativa · 46 temp. ambiente · 47 borboleta absoluta B · 49/4A pedal D/E · 4D tempo com MIL · 51 tipo de combustível · 52 etanol · 5C temp. óleo · 5E consumo.

### Falhas (DTC)
- **Ler falhas:** confirmadas (modo 03), pendentes (07) e permanentes (0A), união de todas as centrais que responderem; luz de injeção (MIL) e monitores de prontidão (catalisador, EVAP, sonda lambda etc.).
- **Apagar falhas** (com confirmação): modo 04. Zera também os monitores de prontidão e **não resolve a causa** do defeito. Anote os códigos antes.
- **Descrições:** cada falha mostra a descrição em português (para ~90 códigos genéricos) e as descrições da **tabela Peugeot/Citroën** (em inglês, por família de módulo, com motores a gasolina primeiro).
- **Consultar tabela Peugeot:** caixa de busca por código (`P0420`), prefixo (`P03`) ou palavra em inglês (`misfiring`).
- **Reset da ECU:** veja [Reset da ECU](#reset-da-ecu).

### Info
VIN, tensão medida pelo adaptador, versão do ELM, protocolo negociado e lista de PIDs suportados. Adaptadores clones às vezes devolvem o VIN incompleto; nesse caso aparece o trecho lido com "(parcial — a ECU não enviou o restante)".

### Terminal
Envia comandos AT do adaptador e consultas de leitura dos modos 01, 02, 03, 07, 09 e 0A. Exemplos: `ATRV` (tensão), `ATDP` (protocolo), `010C` (RPM), `0902` (VIN). Qualquer outro comando é recusado.

### Capacidades
Varredura **somente leitura** que descobre quais centrais respondem ao OBD e, para cada uma, lista:

- PIDs do modo 01 suportados, com o valor atual;
- freeze frame (modo 02);
- falhas (03/07/0A);
- resultados de testes internos (modo 06: catalisador, falhas de ignição...);
- identificação (modo 09: VIN, calibração, CVN, nome da ECU);
- leituras UDS: DIDs de identificação (`F190`, `F187`, `F18A`, `F18C`, `F191`, `F193`, `F194`, `F195`, `F197`, `F19E`), `3E 00` e `19 02 FF`.

Leva de 1 a 3 minutos no carro e **pausa a aba Ao vivo** enquanto roda. O resultado aparece na tela e pode ser baixado em `.json`. É esse arquivo que ajuda a decidir novas funções do app.

### Módulos (avançado, somente leitura)
Envia consultas a qualquer módulo CAN pelos IDs de requisição e resposta informados (ex.: `7E0` → `7E8` para o motor).

**Serviços**
- Liberados: `22` (ler DID), `19` (ler falhas UDS), `3E` (tester present), `1A`, `21`, `18`, `17` (leituras KWP) e `10 01` (sessão padrão).
- Bloqueados: escrita, reset, apagar falhas, segurança, atuadores, rotinas, download/upload e troca de sessão ([seção 7](#7-o-que-o-app-não-faz-segurança)).

**Ferramentas da aba**
- **Campos ID req / ID resp:** par de IDs CAN de 11 bits (até 3 dígitos hex). Fora da faixa OBD `7E0–7E7`, o ID de resposta é obrigatório.
- **Comando:** bytes em hexa (ex.: `22F190`), até 8 bytes; botões de comandos prontos.
- **Sondar módulo:** envia `3E00`, `22F190` e `1A87` e mostra as respostas (positivas, negativas com o motivo ou ausência de resposta).
- **Candidatos:** lista de pares de endereços de módulos PSA e o botão **Sondar todos os candidatos** (3 consultas de leitura por módulo, com confirmação):

  | Módulo | Requisição → Resposta | Dica de família |
  |---|---|---|
  | Motor (injeção, família INJ) | `6A8` → `688` | |
  | Motor (OBD padrão) | `7E0` → `7E8` | |
  | BSI (central de carroceria) | `752` → `652` | |
  | ABS / ESP | `6AD` → `68D` | ABS (MDT22) |
  | Airbag | `744` → `644` | Airbag (MDS12) |
  | Painel de instrumentos | `75F` → `65F` | Painel (MDI04, MDI056) |
  | Câmbio automático (BOITEVIT) | `6A9` → `689` | |
  | Direção elétrica (EPS) | `6B5` → `695` | |
  | Central multimídia/telemática | `764` → `664` | |

  Esses pares são comuns em famílias de módulos PSA, **não foram validados neste carro**. Sem resposta não significa defeito: pode ser outro endereço, outro protocolo ou outra rede CAN.
- **Ler falhas do módulo** e **Ler ABS, airbag e painel:** veja a [seção 6](#6-lendo-as-falhas-de-abs-airbag-e-painel).

### Log
Todos os comandos enviados (`TX`) e respostas (`RX`), com tempo em ms, erros e eventos de conexão (`INFO`). As leituras automáticas da aba Ao vivo ficam ocultas por padrão (marque "Mostrar leituras ao vivo"). Tem rolagem automática, **Limpar** e **Baixar .txt**, útil para relatar problemas.

### Reset da ECU
- Envia `ATSH7E0` + `11 01` (hard reset) ou `11 03` (soft reset) à central do motor e restaura o cabeçalho padrão (`ATSH7DF`).
- **Só com motor desligado e ignição ligada.** O app bloqueia se o RPM for maior que 50, se não houver leitura recente de RPM, ou se a velocidade for maior que 0, e pede confirmação.
- A central pode **recusar** (ex.: `7F 11 22` condições incorretas, `7F 11 33` acesso negado, `7F 11 7F` serviço não suportado na sessão) ou **não responder**; o resultado, o motivo e a resposta crua aparecem na tela e no log.
- Não há garantia de que a central do Cactus aceite esse serviço pela porta OBD. O reset **não apaga falhas**, pode derrubar a comunicação por alguns segundos e o app só reconecta se você clicar em Conectar novamente.

## 6. Lendo as falhas de ABS, airbag e painel

Pré-requisitos: motor **desligado**, ignição ligada, app conectado.

1. Abra a aba **Módulos** e clique em **Ler ABS, airbag e painel**, ou escolha um módulo em *Candidatos* e clique em **Ler falhas do módulo**.
2. Para cada módulo o app tenta, nesta ordem, parando na primeira resposta positiva:

   | Tentativa | Comando | Padrão |
   |---|---|---|
   | 1 | `19 02 FF` | UDS ReadDTCInformation, todas as falhas |
   | 2 | `19 02 09` | UDS, só falhas ativas/confirmadas |
   | 3 | `17 FF 00` | KWP ReadStatusOfDTC, todos os grupos |
   | 4 | `18 00 FF 00` | KWP ReadDTCByStatus |

3. A tela mostra: o banner de **interpretação provisória**, as tentativas e o resultado de cada uma, o formato lido (UDS ou KWP) e a tabela de falhas.

**Colunas da tabela**

| Coluna | Significado |
|---|---|
| Bruto | Bytes do registro como o módulo enviou (UDS: 3 bytes de código + 1 de status; KWP: 2 de código + 1 de status) |
| Código | Código bruto de 2 bytes (ex.: `8610`) e o mesmo valor no formato SAE (ex.: `B0610`) |
| Status | UDS: bits decodificados (ISO 14229, veja abaixo). KWP: byte mostrado cru, pois o significado depende do módulo |
| Descrição | Descrições da tabela Peugeot casando o código bruto, o formato SAE ou o código de 3 bytes. ★ marca a família do tipo de módulo escolhido (airbag: MDS12; ABS: MDT22; painel: MDI04/MDI056) |

**Bits do status UDS:** `01` falha ativa agora · `02` falhou neste ciclo · `04` pendente · `08` confirmada · `10` teste não concluído desde a limpeza · `20` falhou desde a limpeza · `40` teste não concluído neste ciclo · `80` luz de aviso solicitada.

**Por que é provisório:** o formato (UDS/KWP) segue o padrão, mas ainda não se sabe, num Cactus real, se o código que o módulo envia corresponde ao código da tabela Peugeot, nem se os endereços candidatos são esses. Se nenhum código casar, a coluna mostra "sem correspondência na tabela"; confie no dado bruto. Para ajudar a confirmar, veja a [seção 14](#14-como-ajudar-a-validar-no-seu-carro).

## 7. O que o app não faz (segurança)

O app **não** implementa e **bloqueia** na API:

- escrita de dados, codificação/telecodificação, acesso de segurança (seed/key), controle de atuadores e rotinas, controle de comunicação, controle de DTC, troca de sessão (exceto `10 01`), download/upload e gravação de firmware;
- reset e apagamento de falhas de módulos que não sejam a central do motor;
- varredura automática de endereços CAN (só os candidatos listados, por ação explícita sua);
- comandos fora da lista de leitura no Terminal (somente AT e modos 01, 02, 03, 07, 09, 0A).

O apagamento de falhas (modo 04) e o reset da ECU (UDS `11`) existem apenas para a **central do motor**, com confirmação e, no reset, travas de RPM e velocidade. Funções de escrita ou reset em outros módulos só devem ser consideradas depois de validar respostas reais do seu carro, módulo por módulo.

## 8. Testar sem o carro (simulador)

Abra dois terminais na pasta do projeto:

```
# terminal 1
python simulator.py

# terminal 2
python app.py --host 127.0.0.1 --port 35000
```

No painel, use IP `127.0.0.1` e porta `35000`. O simulador gera RPM e velocidade variando e dois códigos de falha (P0420 e P0171). A porta do simulador pode ser trocada: `python simulator.py 36000` (um número como primeiro argumento).

| Opção do simulador | Efeito |
|---|---|
| `--engine-off` | Motor parado (necessário para testar o reset da ECU) |
| `--refuse-reset` | A ECU simulada recusa o reset (`7F 11 22`) |
| `--two-ecus` | Duas centrais (`7E8` e `7E9`) respondendo ao OBD, como no carro real |
| `--short-vin` | Devolve o VIN truncado, como alguns clones |
| `--elm-timing` | Imita o atraso real do ELM327 (~200 ms por resposta, ~400 ms com duas centrais), para medir o efeito da leitura rápida |

Também simula, quando os cabeçalhos estão ativos, módulos fictícios:

| Módulo simulado | Requisição → Resposta | Comportamento |
|---|---|---|
| Genérico | `6A8` → `688` | Responde `3E00` e `22F190`; recusa o resto com `7F xx 11` |
| Airbag | `744` → `644` | UDS `19`: 2 falhas (`8610`, `7363`) |
| ABS | `6AD` → `68D` | KWP `17`: 2 falhas (`0562`, `0606`) |

Exemplo para testar tudo: `python simulator.py --engine-off --two-ecus`

## 9. Solução de problemas

| Sintoma | O que verificar |
|---|---|
| `Não foi possível conectar ... (timed out)` | O computador não está no Wi-Fi do adaptador, o adaptador está sem energia, ou o IP é outro. Confira o gateway e use esse IP no painel. |
| Conecta, mas "a ECU não respondeu" / `UNABLE TO CONNECT` | Ligue a ignição ou o motor e tente de novo. Veja a aba **Log**. |
| `python3` não é encontrado (Windows) | Use `python app.py`. |
| Painel não abre / porta ocupada | Confirme que o terminal mostra `Painel: http://localhost:8080` e que nada mais usa a porta 8080 (ou use `--web-port 9000`). Uma instância antiga do app ainda aberta pode segurar a porta e servir uma versão desatualizada: feche-a (Ctrl+C no terminal) e abra de novo. |
| Mensagem "not found" ao usar uma função nova | Quase sempre é uma instância antiga do `app.py` ainda rodando; feche e inicie de novo. |
| Firewall do Windows pergunta sobre o Python | Pode permitir somente em rede privada. |
| VIN vazio, parcial ou falhas incompletas | Clones às vezes falham em respostas longas. Veja a resposta crua no Terminal ou no Log. |
| Códigos de falha estranhos (ex.: `C0300`) | Já corrigido: duas centrais respondem ao mesmo pedido e as respostas eram coladas. Se aparecer de novo, envie o log. |
| Alguns dados não aparecem em "Ao vivo" | A central não declara suporte a esse PID. Veja a lista na aba Info. |
| Valor some por um instante em "Ao vivo" | Cerca de 3% das leituras voltam `NO DATA`; o app tenta de novo e mantém o último valor. |
| Módulo não responde na aba Módulos | O par de endereços pode ser outro, o módulo pode usar KWP em vez de UDS, estar numa sessão de diagnóstico diferente ou em outra rede CAN que o adaptador não alcança. |
| Respostas `7F xx 11` / `7F xx 12` / `7F xx 31` | Serviço, subfunção ou DID não suportados por aquele módulo. É uma resposta normal, não um erro do app. |
| Respostas `7F xx 22` / `7F xx 33` | Condições incorretas (ex.: motor ligado) ou acesso negado (a sessão atual não permite). |
| O adaptador cai após um reset da ECU | Normal por alguns segundos. Aguarde e clique em Conectar de novo. |

## 10. Como o app funciona por dentro

**Comunicação.** O app abre um socket TCP no adaptador e envia comandos terminados em `\r`. Na conexão: `ATZ`, `ATE0` (sem eco), `ATL0` (sem quebra de linha), `ATS0` (sem espaços), `ATH0` (sem cabeçalhos), `ATAT1` (tempo adaptativo) e `ATSP0` (protocolo automático); depois `ATDPN` confirma o protocolo (no Cactus: `6` = ISO 15765-4 CAN 11 bit/500 kbps).

**Duas centrais respondem.** Um pedido funcional (`ATSH7DF`) é respondido pela central do motor (`7E8`) e por outra (`7E9`). Com cabeçalhos desligados (`ATH0`) não dá para saber quem respondeu o quê, então o app interpreta **cada resposta separadamente** (inclusive o formato multi-frame `014/0:/1:`), usa a primeira para os dados ao vivo e junta (união, sem repetir) as falhas de todas.

**Multi-frame (ISO-TP).** Respostas longas (VIN, falhas, UDS) chegam em vários quadros. Nas varreduras o app liga `ATH1` (cabeçalhos) e remonta os quadros pelos PCI `0x`/`1x`/`2x`; nas consultas a módulos configura também o controle de fluxo (`ATFCSH`, `ATFCSD`, `ATFCSM1`) e restaura tudo (`ATFCSM0`, `ATAR`, `ATH0`, `ATSH7DF`) no final, mesmo em caso de erro.

**Segurança de threads.** Uma trava (`RLock`) garante que sequências de comandos (ex.: `ATSH`+pedido+restauração) não se misturem com a leitura ao vivo, que roda em uma *thread* própria. Os comandos da leitura ao vivo aparecem no log com a origem `poll`.

**Log.** Buffer circular de 5.000 entradas com índice crescente; o painel consulta `?since=N` para trazer só as novas. Tipos: `TX` (enviado), `RX` (recebido), `INFO` e erros, com tempo de resposta em ms.

**Painel.** Uma única página HTML/JS/CSS sem dependências externas, servida por `http.server`. Não precisa de internet.

## 11. API HTTP local

Útil para scripts. Todas as respostas são JSON; erros voltam como `{"error": "..."}` com status 400 (erro tratado) ou 500.

| Método | Rota | Corpo / parâmetros | Função |
|---|---|---|---|
| GET | `/` | | Painel |
| GET | `/api/status` | | Conexão, host, porta, versão do adaptador, protocolo e `app_version` |
| GET | `/api/connection-log` | | Últimos 200 eventos do log permanente de conexões |
| GET | `/api/changelog` | | Versão atual e texto do CHANGELOG.md |
| GET | `/api/live` | | Valores ao vivo atuais e `status` (luz de injeção e nº de falhas, atualizado a cada poucos segundos) |
| GET | `/api/dtcs` | | Falhas (03/07/0A), status MIL e descrições (inclui `peugeot`) |
| GET | `/api/info` | | VIN, tensão, PIDs suportados, versão, protocolo |
| GET | `/api/log?since=N` | `since` | Entradas do log a partir do índice N |
| GET | `/api/dtc-search?q=` | `q` | Busca na tabela Peugeot |
| GET | `/api/scan/status` | | Andamento do diagnóstico de capacidades |
| GET | `/api/scan/result` | | Resultado (JSON) do último diagnóstico |
| POST | `/api/connect` | `{host, port}` | Conecta ao adaptador |
| POST | `/api/disconnect` | | Desconecta |
| POST | `/api/clear` | `{confirm: true}` | Apaga falhas (modo 04) |
| POST | `/api/ecu-reset` | `{confirm: true, ecu_id, sub}` | Reset da ECU (`sub` = `01` ou `03`) |
| POST | `/api/raw` | `{cmd}` | Terminal (AT e modos de leitura) |
| POST | `/api/log/clear` | | Limpa o log |
| POST | `/api/fast` | `{on: true\|false}` | Liga ou desliga a leitura rápida (`/api/live` informa `fast` e `rate`, em leituras/s) |
| POST | `/api/scan/start` | | Inicia o diagnóstico de capacidades |
| POST | `/api/uds` | `{req_id, resp_id, cmd}` | Consulta somente leitura a um módulo |
| POST | `/api/module-dtcs` | `{req_id, resp_id, hint}` | Lê e interpreta as falhas de um módulo (`hint`: `abs`, `airbag`, `cluster`) |

Exemplo (com o app conectado):

```
curl http://localhost:8080/api/live
curl -X POST http://localhost:8080/api/uds -d '{"req_id":"7E0","resp_id":"7E8","cmd":"22F190"}'
```

## 12. Tabela de falhas Peugeot

`dtc_peugeot.json` tem duas chaves: `families` (54 famílias de módulos, ex.: MDE12/14/42/44/46/48 para motores a gasolina, MDS12 airbag, MDT22 ESP/ABS Bosch 8.1, MDI04 painel) e `codes` (2.632 códigos com descrição em inglês e as famílias em que aparecem).

- **Busca por código:** o código é procurado como informado. Nas falhas do motor, famílias de motor a gasolina vêm primeiro; nos módulos, a família do tipo escolhido (★) vem primeiro.
- **Busca por texto:** em inglês, na caixa "Consultar tabela Peugeot".
- **Arquivo opcional:** a tabela é um arquivo local (`dtc_peugeot.json`, na pasta do projeto) que **não é distribuído com o repositório**. Sem ele o app funciona normalmente, só sem essas descrições, e a caixa de busca da tabela fica escondida.
- A tabela **não é específica do Cactus**: o mesmo código pode ter textos diferentes conforme a família do módulo. Use a descrição como pista, não como diagnóstico.

## 13. Limites conhecidos

- A base é **OBD-II padrão (SAE J1979)** sobre ISO 15765-4 CAN (11 bit, 500 kbps), negociado automaticamente (`ATSP0`). O ELM327 não alcança redes CAN de 125 kbps em outros pinos do conector.
- O C4 Cactus tem **mais de uma central respondendo** ao OBD (motor e outra). Os dados ao vivo usam a primeira que responde; as falhas são a união de todas, sem indicar de qual central veio cada código.
- Sem MAF, nível de combustível e temperatura do óleo pela porta OBD neste carro (confirmado no teste real).
- Cerca de 3% das leituras podem voltar `NO DATA` ao acaso; o app tenta de novo e mantém o último valor.
- Alguns clones ELM327 devolvem o VIN truncado ou falham em respostas longas; o app avisa quando a resposta vem parcial.
- Descrição em português só para cerca de 90 códigos genéricos comuns; a tabela Peugeot está em inglês.
- Resultados de leitura de módulos além da central do motor são **provisórios** até serem confirmados em um carro real: endereços candidatos, formato UDS/KWP e correspondência com a tabela.
- Leitura passiva do barramento CAN (`ATMA`) não está implementada.
- Não há login no painel: ele só aceita conexões de `127.0.0.1`.

### Limitações do adaptador ELM327

O app usa um adaptador ELM327 Wi-Fi. Esse tipo de adaptador tem limites próprios que **não dependem do programa**:

| Limitação | Efeito no app |
|---|---|
| **Uma rede CAN por vez, nos pinos 6/14** (CAN de alta velocidade) | Só enxerga o que está nesse barramento: no Cactus, a central do motor (`7E8`) e uma segunda que quase não responde (`7E9`). ABS, airbag, painel e BSI ficam em outro barramento e, em geral, **não aparecem**. |
| **Sem troca de pinos nem de velocidade** | Não alcança o CAN de carroceria (que em carros PSA costuma ser mais lento e usar outros pinos). Esse dado **não foi confirmado** para o Cactus. |
| **O BSI pode bloquear o acesso** | Relatos de comunidade indicam que o BSI funciona como filtro entre a porta OBD e os outros módulos. Isso explicaria as consultas UDS sem resposta no teste real, mas é uma hipótese. |
| **Protocolo OBD-II genérico** | Lê dados padrão do motor, falhas (03/07/0A) e identificação. Funções de oficina (coding, atuadores, leitura estendida de módulos) exigem ferramenta específica da marca. |
| **Velocidade baixa** | Cada leitura é uma pergunta e uma resposta por vez, com tempo limite do adaptador. Dá algumas dezenas de leituras por segundo, e a leitura ao vivo faz rodízio dos PIDs lentos. |
| **Clones variam em qualidade** | Os mais baratos truncam respostas longas (como o VIN), perdem leituras (`NO DATA`) e têm firmware pela metade. |
| **Adaptadores "especiais" não garantem cobertura** | Modelos com chave HS/MS CAN foram feitos para outras marcas (por exemplo Ford). Eles não resolvem os módulos PSA só por terem a chave. |

**O que fazer para ler os outros módulos:** o caminho realista é uma interface/ferramenta com suporte a PSA (por exemplo Lexia/DiagBox ou scanner multimarca com módulo PSA) ou uma interface CAN própria ligada ao barramento certo. Esse tipo de acesso **não é possível com um ELM327 comum** e não está implementado neste projeto. Antes de comprar qualquer adaptador, rode a aba **Módulos** no seu carro: se nenhum candidato responder, o ELM327 não alcança esses módulos.

## 14. Como ajudar a validar no seu carro

Para evoluir as funções de módulos, o que mais ajuda são respostas reais. Com o carro parado, motor desligado e ignição ligada:

1. Aba **Capacidades** → rode o diagnóstico e baixe o `.json`.
2. Aba **Módulos** → **Sondar todos os candidatos**.
3. Aba **Módulos** → **Ler ABS, airbag e painel**.
4. Aba **Log** → **Baixar .txt**.
5. Anote o que o painel do carro mostra no momento (luzes de ABS, airbag, mensagens no visor) para comparar com o que o app leu.

Guarde os três arquivos (`.json`, log `.txt` e uma captura da tela de Módulos). Com eles dá para confirmar quais pares de endereços respondem, qual formato cada módulo usa e se os códigos casam com a tabela.

## 15. Desenvolvimento e publicação no GitHub

- Sem dependências externas: apenas biblioteca padrão do Python. Código comentado em português.
- Testes manuais usando o simulador (seção 8); não há suíte automatizada ainda.
- O repositório inclui `.gitignore` (ignora `__pycache__/`, ambientes virtuais, logs, `logs/` e diagnósticos baixados).

Primeira publicação:

```
git init
git add .
git commit -m "psa_obd: diagnóstico OBD2 PSA via Wi-Fi"
git branch -M main
git remote add origin https://github.com/leogvital/C4-Cactus-OBD2.git
git push -u origin main
```

Antes de publicar:

- **Licença:** veja a [seção 20](#20-licença).
- **Tabela de falhas:** o `dtc_peugeot.json` não é versionado nem publicado; veja a seção 16.
- **Dados pessoais:** não suba logs ou JSONs de diagnóstico do seu carro sem revisar, pois contêm o **VIN** (chassi) e identificadores das centrais.

## 16. Dados de terceiros e créditos

- **`dtc_peugeot.json`** (opcional) é derivado de uma tabela de falhas Peugeot/Citroën em PDF (exportação de planilha), fornecida pelo autor do projeto. A origem e a licença dessa tabela não estão definidas aqui, por isso o arquivo **não é distribuído com este repositório**: ele fica só no computador do autor (fora do git). O app funciona sem ele, apenas sem as descrições da tabela.
- Os **pares de endereços dos módulos candidatos** vêm do projeto público [arduino-psa-diag](https://github.com/ludwig-v/arduino-psa-diag) (`ECU_LIST.md`). Apenas a lista de endereços foi usada; as funções de escrita, reset e gravação desse projeto **não** foram incorporadas. Confira a licença dele ao redistribuir.
- Referências consultadas (nenhum código copiado): [autowp.github.io](https://autowp.github.io/) (quadros CAN de carroceria da PSA, modelos antigos, não é diagnóstico) e [PSAVanCanBridge](https://github.com/morcibacsi/PSAVanCanBridge) (ponte VAN↔CAN).
- Padrões usados: SAE J1979 / ISO 15031 (OBD-II), ISO 15765-4 e ISO 15765-2 (CAN e ISO-TP), ISO 14229 (UDS), ISO 14230 (KWP2000), conjunto de comandos ELM327.
- "Peugeot", "Citroën", "PSA" e "ELM327" são marcas de seus respectivos titulares; este projeto não tem vínculo com eles.

## 17. Glossário

| Termo | Significado |
|---|---|
| **ECU / central / módulo** | Computador de bordo de um sistema (motor, ABS, airbag...) |
| **DTC** | *Diagnostic Trouble Code*, código de falha (P = motor/câmbio, C = chassi, B = carroceria, U = rede) |
| **MIL** | Luz de injeção/diagnóstico no painel |
| **PID** | Identificador de um dado ao vivo (ex.: `0C` = RPM) |
| **OBD-II / J1979** | Padrão de diagnóstico de emissões, base das leituras do app |
| **CAN** | Rede de comunicação entre módulos (aqui 11 bit, 500 kbps) |
| **ISO-TP** | Transporte que divide respostas longas em vários quadros CAN |
| **UDS** | Protocolo de diagnóstico moderno (ISO 14229); serviços como `22` e `19` |
| **KWP** | Protocolo de diagnóstico anterior (ISO 14230); usado por alguns módulos mesmo sobre CAN |
| **DID** | Identificador de dado do serviço UDS `22` (ex.: `F190` = VIN) |
| **NRC** | Código de resposta negativa (`7F <serviço> <NRC>`) |
| **ELM327** | Chip/adaptador que faz a ponte entre o computador e o carro |
| **AT** | Comandos de configuração do adaptador (`ATZ`, `ATSH`...) |
| **Hard / soft reset** | `11 01` / `11 03`: reinício completo / parcial da central |
| **Freeze frame** | Foto dos dados do motor no momento em que a falha ocorreu |
| **Monitores de prontidão** | Testes internos de emissões (catalisador, EVAP, lambda...) que precisam estar completos |

## 18. Log permanente de conexões

Todo uso da conexão com a central é gravado em **`logs/conexoes.log`** (criado ao lado do `app.py`), uma linha por evento, sempre acrescentando ao fim, com data, hora e fuso. Diferente do log da aba **Log** (memória, últimas 5.000 linhas, some ao fechar o app), este arquivo **não é apagado pelo app**. Também aparece na aba **Histórico**.

```
2026-10-17 23:09:57-03:00 | CONECTAR_OK | 192.168.0.10:35000 | ELM327 v1.5 | protocolo 6
2026-10-17 23:10:00-03:00 | RESET_ECU | 192.168.0.10:35000 | ECU 7E0 | sub 01 | ok
2026-10-17 23:12:41-03:00 | DESCONECTAR | 192.168.0.10:35000 | motivo: usuário | duração 14min44s
```

| Evento | Quando |
|---|---|
| `APP_INICIO` / `APP_FIM` | Início e encerramento do app (com a versão) |
| `CONECTAR_OK` / `CONECTAR_FALHA` | Tentativa de conexão, com adaptador e protocolo ou o erro |
| `DESCONECTAR` / `CONEXAO_PERDIDA` | Fim da conexão, com motivo e duração |
| `APAGAR_FALHAS` / `RESET_ECU` | Ações que alteram a central |
| `DIAGNOSTICO_INICIO` / `DIAGNOSTICO_FIM` | Varredura de capacidades |
| `CONSULTA_MODULO` / `FALHAS_MODULO` / `TERMINAL` | Consultas manuais (aba Módulos e Terminal) |
| `LEITURA_RAPIDA` | Leitura rápida ligada ou desligada |

O arquivo não guarda VIN nem leituras do veículo. A pasta `logs/` está no `.gitignore`: o histórico fica no seu computador e não vai para o GitHub.

## 19. Versionamento e publicação

O app segue [SemVer](https://semver.org/lang/pt-BR/) (`MAIOR.MENOR.CORREÇÃO`). A versão está em `version.py`, aparece no cabeçalho do painel, em `/api/status` e ao iniciar o app. O histórico completo está em [CHANGELOG.md](CHANGELOG.md) e na aba **Histórico**.

A cada publicação:

```
python tools/release.py patch "correção de X"          # 1.1.0 -> 1.1.1
python tools/release.py minor "nova função Y"          # 1.1.0 -> 1.2.0
python tools/release.py major "mudança incompatível"   # 1.1.0 -> 2.0.0
git push origin HEAD --follow-tags                      # ou acrescente --push ao comando acima
```

O script atualiza `version.py` e `CHANGELOG.md`, faz o commit e cria a etiqueta `vX.Y.Z`. Para detalhar a entrada do changelog, escreva as mudanças antes sob um título `## [Não publicado]` em `CHANGELOG.md`; o script troca esse título pela versão e pela data. Ele recusa publicar se não houver alterações.

Repositório: https://github.com/leogvital/C4-Cactus-OBD2

## 20. Licença

Código sob a **PolyForm Noncommercial License 1.0.0** (texto completo em [LICENSE](LICENSE)): você pode usar, estudar, copiar e modificar o programa para **fins pessoais e outros não comerciais**. **Uso comercial não é permitido.** O código é público para leitura e uso pessoal, mas essa licença não é de código aberto no sentido da OSI, justamente por proibir o uso comercial.

Para qualquer uso comercial, entre em contato com o autor pelo GitHub: https://github.com/leogvital
