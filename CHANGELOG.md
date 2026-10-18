# Histórico de versões

Formato [SemVer](https://semver.org/lang/pt-BR/): `MAIOR.MENOR.CORREÇÃO`. Cada publicação recebe uma versão aqui, uma etiqueta `vX.Y.Z` no git e o número é exibido no painel. Para publicar: `python tools/release.py <patch|minor|major> "resumo"`.

## [1.4.0] - 2026-10-18
- Painel em tela cheia (botão ou tecla F), com ocultação automática dos botões e tela sempre ligada

## [1.3.0] - 2026-10-18
- Painel com dois layouts (Digital estilo painel moderno e Clássico) com seletor; digital traz gráfico ao vivo, trajeto, velocidade média/máxima e tempo

## [1.2.2] - 2026-10-18
- Painel: 'água' passa a se chamar 'temperatura do motor' (mostrador, luz de aviso e documentação)

## [1.2.1] - 2026-10-18
- Renomeia o botão 'Teste dos instrumentos' para 'Animação de teste' e deixa claro que é só visual e não testa o painel do carro

## [1.2.0] - 2026-10-18
### Novo
- **Aba Painel**: instrumentos animados (conta-giros, velocímetro, temperatura da água, combustível), luzes de aviso (injeção, falhas, carga, água, combustível), cartões de tensão/carga/borboleta/pedal/etc., modo demonstração e teste dos instrumentos. A aba abre por padrão.
- Mini-gráficos de histórico nos cartões da aba **Ao vivo**.
- `/api/live` passa a devolver `status` (luz de injeção e nº de falhas), lido periodicamente da central.

## [1.1.4] - 2026-10-18
- Documenta as limitações do adaptador ELM327 no README e avisa na aba Módulos que ABS, airbag, painel e BSI normalmente não respondem

## [1.1.3] - 2026-10-17
- README volta a documentar a tabela de falhas Peugeot/Citroën (arquivo opcional local, não distribuído no repositório)

## [1.1.2] - 2026-10-17
- Restaura as descrições da tabela de falhas como recurso opcional: usa o arquivo local, se existir; sem ele o app funciona e esconde a busca

## [1.1.1] - 2026-10-17
- Remove do código a consulta à tabela externa de falhas e o seletor de tipo de módulo; falhas de módulos mostram só o dado lido (bruto, código SAE e status)

## [1.1.0] - 2026-10-17
### Novo
- **Log permanente de conexões** (`logs/conexoes.log`): data, hora e fuso de cada conexão, falha, desconexão, queda, início/fim do app, apagar falhas, reset da ECU, diagnóstico de capacidades e consultas a módulos. Não grava VIN.
- **Versionamento**: número da versão no cabeçalho do painel, em `/api/status` e no terminal ao iniciar; aba **Histórico** com o log de conexões e este changelog; script `tools/release.py`.
- Decodificação dos PIDs `03` (estado do sistema de combustível), `1C` (norma OBD) e `51` (tipo de combustível), vistos no teste real no Cactus.

### Corrigido
- O **reset da ECU** (UDS 11) chamava um método que não existia em `elm327.py` e falharia com erro 500; agora está implementado, só para IDs 7E0–7E7 e subserviços 01/03.

### Licença
- Adicionada a PolyForm Noncommercial 1.0.0: uso pessoal e não comercial.

### Validado no carro (Cactus 2022 1.6, 17/10/2026)
- Aba **Capacidades**: varredura concluída; motor (7E8) com 28 PIDs; segunda central (7E9) responde ao ping mas sem PIDs. UDS (22/19/3E) sem resposta em 7E0 e 7E1.

## [1.0.0] - 2026-10-17
- Versão inicial: dados ao vivo, falhas (03/07/0A), apagar falhas, info/VIN, terminal, capacidades, módulos UDS/KWP somente leitura, log de comandos e simulador.
